# file_operations.py
import datetime
import os
from google.cloud import storage

def get_storage_client():
    try:
        client = storage.Client()
    except Exception as e:
        raise RuntimeError(f'Error creating storage client: {e}')
    return client

def upload_to_bucket(bucket_name, local_file, remote_file):
    client = get_storage_client()
    bucket = client.get_bucket(bucket_name)
    blob = bucket.blob(remote_file)
    
    # Set eTag and Last-Modified headers
    current_time = datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")
    blob.metadata = {
        "Cache-Control": "public, max-age=86400",
        "ETag": f"{hash(datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ'))}",
        "Last-Modified": current_time,
    }

    try:
        blob.upload_from_filename(local_file, content_type="audio/mpeg")
    except Exception as e:
        raise RuntimeError(f'Error uploading to bucket: {e}')

def get_file_size(bucket_name, blob_name):
    client = get_storage_client()
    bucket = client.get_bucket(bucket_name)
    blob = storage.Blob(blob_name, bucket)
    blob.reload()
    return blob.size

def read_file(file_path):
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"No such file: '{file_path}'")
    with open(file_path, "r") as f:
        return [line.strip() for line in f]

def read_urls_from_file(file_path):
    return read_file(file_path)

def read_cache(file_path):
    return read_file(file_path)

def update_cache(file_path, url):
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"No such file: '{file_path}'")
    with open(file_path, "a") as f:
        f.write(url + "\n")

def create_bucket_object(bucket_name):
    try:
        storage_client = storage.Client()
        bucket = storage_client.get_bucket(bucket_name)
        return bucket
    except Exception as e:
        print(f"Error creating bucket object: {e}")
        return None

def upload_to_bucket(bucket_name, local_file, remote_file):
    try:
        storage_client = get_storage_client()
        bucket = storage_client.get_bucket(bucket_name)
        blob = bucket.blob(remote_file)
        blob.upload_from_filename(local_file)
        print(f"File {local_file} uploaded to {remote_file}.")
    except Exception as e:
        print(f"Error uploading file to bucket: {e}")
        return None

def download_from_bucket(bucket_name, remote_file, local_file):
    try:
        storage_client = get_storage_client()
        bucket = storage_client.get_bucket(bucket_name)
        blob = bucket.blob(remote_file)
        blob.download_to_filename(local_file)
        print(f"File {remote_file} downloaded to {local_file}.")
    except Exception as e:
        print(f"Error downloading file from bucket: {e}")
        return None