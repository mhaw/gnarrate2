# article_processing.py
import csv
import datetime
import os
import pathlib
from newspaper import Article
from pathlib import Path
import eyed3
import uuid
import logging
import traceback
from functools import wraps
from speech_gen import text_to_speech
from file_operations import upload_to_bucket, update_cache

def extract_articles(urls):
    articles = []
    for url in urls:
        try:
            article = Article(url)
            article.download()
            article.parse()

            # Use UUID to create a unique filename
            content_file = Path("content") / f"article_{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}_{uuid.uuid4()}.txt"
            content_file.parent.mkdir(parents=True, exist_ok=True)
            with content_file.open("w", encoding="utf-8") as f:
                f.write(article.text)

            articles.append({
                "url": url,
                "title": article.title,
                "authors": article.authors,
                "publish_date": article.publish_date,
                "text": article.text,
                "content_file": str(content_file)
            })

        except Exception as e:
            logging.error(f"Error extracting article from '{url}': {e}")

    return articles

def get_audio_info(output_file):
    try:
        audio_info = {}
        audio_file = eyed3.load(output_file)
        if audio_file is not None:
            audio_info["title"] = audio_file.tag.title
            audio_info["artist"] = audio_file.tag.artist
            audio_info["duration"] = audio_file.info.time_secs
        else:
            raise ValueError(f"Invalid audio file: {output_file}")

        return audio_info
    except FileNotFoundError:
        logging.error(f"File not found: {output_file}")
        raise
    except Exception as e:
        logging.error("Error while retrieving audio information:")
        logging.error(f"Output file: {output_file}")
        logging.error(traceback.format_exc())
        raise

def log_entry(log_file, entry):
    try:
        file_exists = pathlib.Path(log_file).is_file()
        with open(log_file, mode="a", newline="", encoding="utf-8") as f:
            fieldnames = ["date_time", "url", 'title', 'artist', 'duration', "word_count", "audio_length", "audio_filename", "status", "error"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)

            if not file_exists:
                writer.writeheader()

            writer.writerow(entry)
    except Exception as e:
        logging.error(f"Error logging entry: {e}")

def construct_narration_text(article):
    try:
        text = f"{article['title']}. "

        with open(article['content_file'], "r", encoding="utf-8") as f:
            content = f.read()

        text += content
        article['description'] = article['title']  # Set the article title as the description if it's missing
        return text
    except Exception as e:
        print(f"Error constructing narration text for article '{article['url']}': {e}")
        return None

def process_article(article, bucket_name, config, select_natural_voice):
    log_file = "processing_log.csv"
    cache_file = "processed_urls_cache.txt"

    log_entry_data = get_initial_log_entry_data(article)
    article["audio_url"] = ""

    try:
        output_file = generate_audio_file(article, config, construct_narration_text, text_to_speech, select_natural_voice)
        log_entry_data.update(get_audio_info(output_file))

        remote_file = upload_audio_file(bucket_name, output_file)
        update_article_info(article, output_file, remote_file, bucket_name)

    except Exception as e:
        logging.error(f"Error processing article: {e}")
        log_entry_data["status"] = "failed"
        log_entry_data["error"] = str(e)  # Capture the error message instead of the traceback
        log_entry(log_file, log_entry_data)
        update_cache(cache_file, article["url"])
        return None  # Return None instead of the error string

    log_entry(log_file, log_entry_data)

    update_cache(cache_file, article["url"])

    return None

def get_initial_log_entry_data(article):
    return {
        "date_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "url": article["url"],
        "word_count": len(article["text"].split()),
        "audio_length": 0,
        "audio_filename": "",
        "status": "success",
    }

def error_handler(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logging.error(f"Error while running {func.__name__}: {e}")
            logging.error(traceback.format_exc())
            raise
    return wrapper

def generate_file_name():
    timestamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    return f"output/article_{timestamp}.mp3"

def create_output_dir(output_dir):
    os.makedirs(output_dir, exist_ok=True)  # Create the output directory if it doesn't exist
    logging.info(f"Output directory {output_dir} has been created or already exists.")

def validate_file(output_file):
    if os.path.isfile(output_file):
        file_size = os.path.getsize(output_file)
        logging.info(f"Output file exists: {output_file}")
        logging.info(f"File size: {file_size} bytes")
    else:
        logging.error(f"Output file not found: {output_file}")
        raise FileNotFoundError(f"File not found: {output_file}")

@error_handler
def generate_audio_file(article, config, construct_narration_text, text_to_speech, select_natural_voice):
    output_dir = config["podcast_feed"]["output_dir"]
    create_output_dir(output_dir)

    output_file = generate_file_name()
    logging.info("Converting text to speech...")

    try:
        text_to_speech(article, output_file, config, construct_narration_text, select_natural_voice)
    except Exception as e:
        logging.error(f"Text to speech conversion failed: {e}")
        raise

    logging.info("Text to speech conversion completed.")

    validate_file(output_file)

    return output_file

def upload_audio_file(bucket_name, output_file):
    remote_file = f"article_{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}.mp3"
    logging.info("Uploading audio file to Google Cloud Storage...")
    try:
        upload_to_bucket(bucket_name, output_file, remote_file)
    except Exception as e:
        logging.error(f"Failed to upload audio file '{output_file}' to Google Cloud Storage: {e}")
        raise

    logging.info("Audio file uploaded successfully.")
    return remote_file

def update_article_info(article, output_file, remote_file, bucket_name):
    audio_url = f"https://storage.googleapis.com/{bucket_name}/{remote_file}"
    article.update({
        "local_file": output_file,
        "remote_file": remote_file,
        "audio_url": audio_url
    })