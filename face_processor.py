import face_recognition
import numpy as np
from PIL import Image
import io
import json
import uuid
from models import db, Photo, Person, FaceMatch, ProcessingQueue
from config import Config
import boto3
from botocore.exceptions import ClientError

# S3クライアント
s3_client = boto3.client(
    's3',
    aws_access_key_id=Config.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=Config.AWS_SECRET_ACCESS_KEY,
    region_name=Config.AWS_REGION
)


def download_image_from_s3(s3_key):
    """S3から画像をダウンロード"""
    try:
        response = s3_client.get_object(Bucket=Config.AWS_S3_BUCKET, Key=s3_key)
        image_data = response['Body'].read()
        image = Image.open(io.BytesIO(image_data))
        return np.array(image)
    except ClientError as e:
        print(f"Error downloading from S3: {e}")
        return None


def upload_to_s3(file_data, s3_key, content_type='image/jpeg'):
    """S3にファイルをアップロード"""
    try:
        s3_client.put_object(
            Bucket=Config.AWS_S3_BUCKET,
            Key=s3_key,
            Body=file_data,
            ContentType=content_type
        )
        return f"{Config.AWS_S3_BUCKET}.s3.{Config.AWS_REGION}.amazonaws.com/{s3_key}"
    except ClientError as e:
        print(f"Error uploading to S3: {e}")
        return None


def create_thumbnail(image_array, max_size=200):
    """サムネイル作成"""
    image = Image.fromarray(image_array)
    image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    
    buffer = io.BytesIO()
    image.save(buffer, format='JPEG', quality=85)
    buffer.seek(0)
    
    return buffer.getvalue()


def process_single_photo(photo_id):
    """1枚の写真を処理（Celeryタスクから呼ばれる）"""
    from app import app
    
    with app.app_context():
        # 処理キューの状態を更新
        queue_item = ProcessingQueue.query.filter_by(photo_id=photo_id).first()
        if not queue_item:
            return {'success': False, 'error': 'Queue item not found'}
        
        queue_item.status = 'processing'
        db.session.commit()
        
        try:
            photo = Photo.query.get(photo_id)
            if not photo:
                raise Exception('Photo not found')
            
            # S3から画像をダウンロード
            image_array = download_image_from_s3(photo.s3_key)
            if image_array is None:
                raise Exception('Failed to download image from S3')
            
            # 顔検出
            face_locations = face_recognition.face_locations(image_array, model='hog')
            face_encodings = face_recognition.face_encodings(image_array, face_locations)
            
            if len(face_encodings) == 0:
                # 顔が見つからない
                photo.processed = True
                photo.face_count = 0
                queue_item.status = 'completed'
                db.session.commit()
                return {'success': True, 'faces_found': 0}
            
            # 既存の人物を取得
            all_persons = Person.query.all()
            known_encodings = []
            known_person_ids = []
            
            for person in all_persons:
                encoding = json.loads(person.face_encoding)
                known_encodings.append(np.array(encoding))
                known_person_ids.append(person.id)
            
            faces_processed = 0
            
            # 各顔を処理
            for face_encoding, face_location in zip(face_encodings, face_locations):
                person_id = None
                
                if len(known_encodings) > 0:
                    # 既存の人物とマッチング
                    matches = face_recognition.compare_faces(
                        known_encodings,
                        face_encoding,
                        tolerance=Config.FACE_RECOGNITION_TOLERANCE
                    )
                    face_distances = face_recognition.face_distance(known_encodings, face_encoding)
                    
                    if True in matches:
                        best_match_index = np.argmin(face_distances)
                        if matches[best_match_index]:
                            person_id = known_person_ids[best_match_index]
                            confidence = 1 - face_distances[best_match_index]
                            
                            # 写真カウントを更新
                            person = Person.query.get(person_id)
                            person.photo_count += 1
                
                # 新しい人物として登録
                if person_id is None:
                    # 顔のサムネイル作成
                    top, right, bottom, left = face_location
                    face_image = image_array[top:bottom, left:right]
                    face_thumbnail = create_thumbnail(face_image)
                    
                    # S3にアップロード
                    thumbnail_key = f"thumbnails/{uuid.uuid4()}.jpg"
                    thumbnail_url = upload_to_s3(face_thumbnail, thumbnail_key)
                    
                    # 新規人物を作成
                    person_id = str(uuid.uuid4())
                    person_count = Person.query.count() + 1
                    new_person = Person(
                        id=person_id,
                        name=f"人物 {person_count}",
                        face_encoding=json.dumps(face_encoding.tolist()),
                        thumbnail_s3_key=thumbnail_key,
                        photo_count=1
                    )
                    db.session.add(new_person)
                    
                    # リストに追加
                    known_encodings.append(face_encoding)
                    known_person_ids.append(person_id)
                    
                    confidence = 1.0
                
                # 顔マッチングを記録
                face_match = FaceMatch(
                    id=str(uuid.uuid4()),
                    photo_id=photo_id,
                    person_id=person_id,
                    bounding_box=json.dumps({
                        'top': int(face_location[0]),
                        'right': int(face_location[1]),
                        'bottom': int(face_location[2]),
                        'left': int(face_location[3])
                    }),
                    confidence=float(confidence),
                    face_encoding=json.dumps(face_encoding.tolist())
                )
                db.session.add(face_match)
                faces_processed += 1
            
            # 写真を処理済みにマーク
            photo.processed = True
            photo.face_count = faces_processed
            queue_item.status = 'completed'
            db.session.commit()
            
            return {'success': True, 'faces_found': faces_processed}
            
        except Exception as e:
            queue_item.status = 'failed'
            queue_item.error_message = str(e)
            db.session.commit()
            return {'success': False, 'error': str(e)}
