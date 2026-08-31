import os
from dotenv import load_dotenv
import cloudinary
import cloudinary.uploader
import cloudinary.api

load_dotenv()

_cloudinary_configured = False


def init_s3(app):
    global _cloudinary_configured
    cloudinary_url = os.environ.get('CLOUDINARY_URL')

    if cloudinary_url and not 'your_cloud_name' in cloudinary_url:
        cloudinary.config(cloudinary_url=cloudinary_url, secure=True)
        _cloudinary_configured = True
        app.config['USE_S3'] = True
    else:
        _cloudinary_configured = False
        app.config['USE_S3'] = False


def is_s3_enabled():
    return _cloudinary_configured


def upload_to_s3(file, folder='uploads'):
    if not is_s3_enabled():
        return None

    result = cloudinary.uploader.upload(file, folder=folder, resource_type='auto')
    return result.get('public_id')


def delete_from_s3(public_id):
    if not is_s3_enabled() or not public_id:
        return False

    try:
        cloudinary.uploader.destroy(public_id)
        return True
    except Exception:
        return False


def get_media_url(filepath):
    if not filepath:
        return ''

    if is_s3_enabled() and not filepath.startswith('static/upload/'):
        return cloudinary.CloudinaryImage(filepath).build_url()

    return f"/{filepath}"
