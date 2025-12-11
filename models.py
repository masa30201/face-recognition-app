from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json

db = SQLAlchemy()

class Photo(db.Model):
    __tablename__ = 'photos'
    
    id = db.Column(db.String(36), primary_key=True)
    file_name = db.Column(db.String(255), nullable=False)
    s3_key = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    processed = db.Column(db.Boolean, default=False)
    face_count = db.Column(db.Integer, default=0)
    thumbnail_s3_key = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    faces = db.relationship('FaceMatch', backref='photo', lazy=True, cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'file_name': self.file_name,
            's3_key': self.s3_key,
            'file_size': self.file_size,
            'upload_date': self.upload_date.isoformat() if self.upload_date else None,
            'processed': self.processed,
            'face_count': self.face_count,
            'thumbnail_url': f"https://{self.thumbnail_s3_key}" if self.thumbnail_s3_key else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class Person(db.Model):
    __tablename__ = 'persons'
    
    id = db.Column(db.String(36), primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    face_encoding = db.Column(db.Text, nullable=False)  # JSON文字列
    thumbnail_s3_key = db.Column(db.String(500))
    photo_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    faces = db.relationship('FaceMatch', backref='person', lazy=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'photo_count': self.photo_count,
            'thumbnail_url': f"https://{self.thumbnail_s3_key}" if self.thumbnail_s3_key else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class FaceMatch(db.Model):
    __tablename__ = 'face_matches'
    
    id = db.Column(db.String(36), primary_key=True)
    photo_id = db.Column(db.String(36), db.ForeignKey('photos.id'), nullable=False)
    person_id = db.Column(db.String(36), db.ForeignKey('persons.id'), nullable=False)
    bounding_box = db.Column(db.Text)  # JSON文字列
    confidence = db.Column(db.Float)
    face_encoding = db.Column(db.Text)  # JSON文字列
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'photo_id': self.photo_id,
            'person_id': self.person_id,
            'bounding_box': json.loads(self.bounding_box) if self.bounding_box else None,
            'confidence': self.confidence,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class ProcessingQueue(db.Model):
    __tablename__ = 'processing_queue'
    
    id = db.Column(db.Integer, primary_key=True)
    photo_id = db.Column(db.String(36), db.ForeignKey('photos.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, processing, completed, failed
    error_message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'photo_id': self.photo_id,
            'status': self.status,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
