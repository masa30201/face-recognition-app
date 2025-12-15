from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
from config import Config
from models import db, Photo, Person, FaceMatch, ProcessingQueue
import uuid
import os
from datetime import datetime
import boto3
from botocore.exceptions import ClientError
from celery import Celery
import face_processor

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY  # セッション用のシークレットキーを設定
CORS(app, supports_credentials=True)  # クッキー/セッションをサポート

# データベース初期化
db.init_app(app)

# Celery初期化
celery = Celery(
    app.name,
    broker=app.config['CELERY_BROKER_URL'],
    backend=app.config['CELERY_RESULT_BACKEND']
)
celery.conf.update(app.config)

# S3クライアント（AWS_ACCESS_KEY_IDが設定されている場合のみ）
s3_client = None
if Config.AWS_ACCESS_KEY_ID and Config.AWS_SECRET_ACCESS_KEY:
    s3_client = boto3.client(
        's3',
        aws_access_key_id=Config.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=Config.AWS_SECRET_ACCESS_KEY,
        region_name=Config.AWS_REGION
    )


# Celeryタスク
@celery.task
def process_photo_task(photo_id):
    """バックグラウンドで写真を処理"""
    with app.app_context():
        return face_processor.process_single_photo(photo_id)


# 認証チェック
def check_auth():
    return session.get('authenticated') == True


# ルート
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/auth', methods=['POST'])
def authenticate():
    """認証"""
    data = request.get_json()
    passphrase = data.get('passphrase', '')
    
    if passphrase == app.config['PASSPHRASE']:
        session['authenticated'] = True
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': '合言葉が正しくありません'}), 401


@app.route('/api/auth/check', methods=['GET'])
def check_authentication():
    """認証状態確認"""
    return jsonify({'authenticated': check_auth()})


@app.route('/api/upload', methods=['POST'])
def upload_photos():
    """写真アップロード"""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    if 'files' not in request.files:
        return jsonify({'error': 'No files provided'}), 400
    
    files = request.files.getlist('files')
    
    max_upload = getattr(Config, 'MAX_UPLOAD_SIZE', 500)
    if len(files) > max_upload:
        return jsonify({'error': f'最大{max_upload}枚まで'}), 400
    
    uploaded = []
    errors = []
    
    for file in files:
        try:
            if file.filename == '':
                continue
            
            # ファイル読み込み
            file_data = file.read()
            file_size = len(file_data)
            
            photo_id = str(uuid.uuid4())
            
            # S3が設定されている場合
            if s3_client and Config.AWS_S3_BUCKET:
                s3_key = f"photos/{photo_id}/{file.filename}"
                
                # S3にアップロード
                s3_client.put_object(
                    Bucket=Config.AWS_S3_BUCKET,
                    Key=s3_key,
                    Body=file_data,
                    ContentType=file.content_type or 'image/jpeg'
                )
            else:
                # ローカル保存（開発用）
                s3_key = f"uploads/{photo_id}_{file.filename}"
                upload_dir = 'uploads'
                os.makedirs(upload_dir, exist_ok=True)
                with open(os.path.join(upload_dir, f"{photo_id}_{file.filename}"), 'wb') as f:
                    f.write(file_data)
            
            # データベースに保存
            photo = Photo(
                id=photo_id,
                file_name=file.filename,
                s3_key=s3_key,
                processed=False,
                face_count=0
            )
            db.session.add(photo)
            
            # 処理キューに追加
            queue_item = ProcessingQueue(
                photo_id=photo_id,
                status='pending'
            )
            db.session.add(queue_item)
            
            uploaded.append(photo.to_dict())
            
        except Exception as e:
            errors.append({'file': file.filename, 'error': str(e)})
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'uploaded': len(uploaded),
        'errors': errors,
        'photos': uploaded
    })


@app.route('/api/process/start', methods=['POST'])
def start_processing():
    """処理開始"""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    # 未処理の写真を取得（最大100枚）
    pending_queue = ProcessingQueue.query.filter_by(status='pending').limit(100).all()
    
    if not pending_queue:
        return jsonify({'message': '処理する写真がありません', 'count': 0})
    
    # Celeryタスクをキューに追加
    for queue_item in pending_queue:
        process_photo_task.delay(queue_item.photo_id)
    
    return jsonify({
        'success': True,
        'message': f'{len(pending_queue)}枚の処理を開始しました',
        'count': len(pending_queue)
    })


@app.route('/api/photos', methods=['GET'])
def get_photos():
    """写真一覧取得"""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 100, type=int)
    
    pagination = Photo.query.order_by(Photo.upload_date.desc()).paginate(
        page=page, per_page=limit, error_out=False
    )
    
    photos = [photo.to_dict() for photo in pagination.items]
    
    # S3の署名付きURL生成
    if s3_client and Config.AWS_S3_BUCKET:
        for photo in photos:
            try:
                photo['url'] = s3_client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': Config.AWS_S3_BUCKET, 'Key': photo['s3_key']},
                    ExpiresIn=3600
                )
            except:
                photo['url'] = None
    
    return jsonify({
        'data': photos,
        'total': pagination.total,
        'page': page,
        'pages': pagination.pages
    })


@app.route('/api/photos/<photo_id>', methods=['GET'])
def get_photo(photo_id):
    """写真詳細取得"""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    photo = Photo.query.get_or_404(photo_id)
    photo_dict = photo.to_dict()
    
    # 署名付きURL生成
    if s3_client and Config.AWS_S3_BUCKET:
        try:
            photo_dict['url'] = s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': Config.AWS_S3_BUCKET, 'Key': photo_dict['s3_key']},
                ExpiresIn=3600
            )
        except:
            photo_dict['url'] = None
    
    return jsonify(photo_dict)


@app.route('/api/persons', methods=['GET'])
def get_persons():
    """人物一覧取得"""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 100, type=int)
    
    pagination = Person.query.order_by(Person.photo_count.desc()).paginate(
        page=page, per_page=limit, error_out=False
    )
    
    persons = [person.to_dict() for person in pagination.items]
    
    # サムネイルの署名付きURL生成
    if s3_client and Config.AWS_S3_BUCKET:
        for person in persons:
            if person.get('thumbnail_s3_key'):
                try:
                    person['thumbnail_url'] = s3_client.generate_presigned_url(
                        'get_object',
                        Params={'Bucket': Config.AWS_S3_BUCKET, 'Key': person['thumbnail_s3_key']},
                        ExpiresIn=3600
                    )
                except:
                    person['thumbnail_url'] = None
    
    return jsonify({
        'data': persons,
        'total': pagination.total,
        'page': page,
        'pages': pagination.pages
    })


@app.route('/api/persons/<person_id>', methods=['PATCH'])
def update_person(person_id):
    """人物名更新"""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    person = Person.query.get_or_404(person_id)
    data = request.get_json()
    
    if 'name' in data:
        person.name = data['name']
        db.session.commit()
    
    return jsonify(person.to_dict())


@app.route('/api/statistics', methods=['GET'])
def get_statistics():
    """統計情報取得"""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    total_photos = Photo.query.count()
    processed_photos = Photo.query.filter_by(processed=True).count()
    total_persons = Person.query.count()
    total_faces = FaceMatch.query.count()
    
    # 処理キューの状態
    pending_count = ProcessingQueue.query.filter_by(status='pending').count()
    processing_count = ProcessingQueue.query.filter_by(status='processing').count()
    failed_count = ProcessingQueue.query.filter_by(status='failed').count()
    
    return jsonify({
        'totalPhotos': total_photos,
        'processedPhotos': processed_photos,
        'totalPersons': total_persons,
        'totalFaces': total_faces,
        'queue': {
            'pending': pending_count,
            'processing': processing_count,
            'failed': failed_count
        }
    })


@app.route('/api/queue/status', methods=['GET'])
def get_queue_status():
    """処理キュー状態取得"""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    pending = ProcessingQueue.query.filter_by(status='pending').count()
    processing = ProcessingQueue.query.filter_by(status='processing').count()
    completed = ProcessingQueue.query.filter_by(status='completed').count()
    failed = ProcessingQueue.query.filter_by(status='failed').count()
    
    return jsonify({
        'pending': pending,
        'processing': processing,
        'completed': completed,
        'failed': failed,
        'total': pending + processing + completed + failed
    })


@app.route('/api/export', methods=['GET'])
def export_data():
    """データエクスポート"""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    photos = Photo.query.all()
    persons = Person.query.all()
    matches = FaceMatch.query.all()
    
    data = {
        'photos': [p.to_dict() for p in photos],
        'persons': [p.to_dict() for p in persons],
        'face_matches': [m.to_dict() for m in matches],
        'export_date': datetime.utcnow().isoformat()
    }
    
    return jsonify(data)


# データベース初期化
with app.app_context():
    db.create_all()


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
