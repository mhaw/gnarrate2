import os
import sys
import time
import requests
import json
from io import BytesIO
from newspaper import Article
from google.cloud import texttospeech, storage
from feedgen.feed import FeedGenerator
from tqdm import tqdm
import math
from pydub import AudioSegment
import datetime
from xml.etree.ElementTree import fromstring
import csv
from pathlib import Path
import eyed3
import feedparser
from datetime import datetime, timezone
import copy

def load_config(file_name="config.json"):
    with open(file_name, "r") as f:
        config = json.load(f)
    return config

config = load_config()

def extract_articles(urls):
    articles = []
    for url in urls:
        article = Article(url)
        article.download()
        article.parse()
        articles.append({
            'title': article.title,
            'content': article.text,
            'url': article.url,
            'date': article.publish_date,
            'published': article.publish_date.strftime('%Y-%m-%dT%H:%M:%S.%fZ') if article.publish_date else None,
            'updated': article.publish_date.strftime('%Y-%m-%dT%H:%M:%S.%fZ') if article.publish_date else None
        })
    return articles

def log_entry(log_file, entry):
    file_exists = Path(log_file).is_file()
    with open(log_file, mode="a", newline="", encoding="utf-8") as f:
        fieldnames = ["date_time", "url", "word_count", "audio_length", "audio_filename", "status"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)

        if not file_exists:
            writer.writeheader()

        writer.writerow(entry)

def text_to_speech(text, output_file):
    client = texttospeech.TextToSpeechClient()

    # Split text into chunks
    max_chunk_size = 4500
    chunks = [text[i:i + max_chunk_size] for i in range(0, len(text), max_chunk_size)]

    audio_segments = []

    for chunk in chunks:
        input_text = texttospeech.SynthesisInput(text=chunk)
        voice = texttospeech.VoiceSelectionParams(
            language_code="en-US", ssml_gender=texttospeech.SsmlVoiceGender.FEMALE
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3
        )

        response = client.synthesize_speech(
            input=input_text, voice=voice, audio_config=audio_config
        )

        # Add response audio content to audio_segments list
        audio_segments.append(AudioSegment.from_file(BytesIO(response.audio_content), format="mp3"))

    # Concatenate audio segments
    combined_audio = sum(audio_segments, AudioSegment.empty())

    # Export concatenated audio to output file
    combined_audio.export(output_file, format="mp3")

def upload_to_bucket(bucket_name, local_file, remote_file):
    client = storage.Client()
    bucket = client.get_bucket(bucket_name)
    blob = bucket.blob(remote_file)
    
    # Set eTag and Last-Modified headers
    current_time = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")
    blob.metadata = {
        "Cache-Control": "public, max-age=86400",
        "ETag": f"{hash(datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ'))}",
        "Last-Modified": current_time,
    }

    blob.upload_from_filename(local_file, content_type="audio/mpeg")

def get_existing_podcast_feed(bucket_name):
    client = storage.Client()
    bucket = client.get_bucket(bucket_name)
    blob = bucket.blob("podcast_feed.xml")

    if blob.exists():
        return blob.download_as_text()
    else:
        return None
    
def get_existing_feed_entries(bucket_name):
    client = storage.Client()
    bucket = client.get_bucket(bucket_name)
    blob = bucket.blob("podcast_feed.xml")

    if not blob.exists():
        return []

    existing_feed_data = blob.download_as_text()
    existing_feed = feedparser.parse(existing_feed_data)

    return existing_feed.entries

import os
from feedgen.feed import FeedGenerator
import feedparser

def create_podcast_feed(bucket_name, articles, config, existing_podcast_feed):
    fg = FeedGenerator()

    if existing_podcast_feed:
        existing_feed = feedparser.parse(existing_podcast_feed)

        if hasattr(existing_feed.feed, 'id'):
            fg.id(existing_feed.feed.id)
        if hasattr(existing_feed.feed, 'title'):
            fg.title(existing_feed.feed.title)
        if hasattr(existing_feed.feed, 'author') and hasattr(existing_feed.feed, 'email'):
            fg.author({"name": existing_feed.feed.author, "email": existing_feed.feed.email})
        if hasattr(existing_feed.feed, 'link'):
            fg.link(href=existing_feed.feed.link, rel="alternate")
        fg.link(href=config["podcast_feed"]["feed_url"], rel="self")
        if hasattr(existing_feed.feed, 'subtitle'):
            fg.subtitle(existing_feed.feed.subtitle)
        if hasattr(existing_feed.feed, 'language'):
            fg.language(existing_feed.feed.language)

        # Add existing feed entries
        for entry in existing_feed.entries:
            fe = fg.add_entry()
            fe.id(entry.id)
            fe.title(entry.title)
            fe.enclosure(entry.enclosures[0].href, 0, "audio/mpeg")
            fe.published(entry.published)
            fe.description(entry.description)
            fe.link(href=entry.link, rel="alternate")
    else:
        fg.id(config["podcast_feed"]["feed_url"])
        # ... (Set up other feed metadata)
        fg.language(config["podcast_feed"]["language"])

    for article in articles:
        fe = fg.add_entry()
        fe.id(article["url"])
        fe.title(article["title"])

        if "remote_file" in article and "local_file" in article:
            remote_file = article["remote_file"]
            mp3_file_url = f"https://storage.googleapis.com/{bucket_name}/{remote_file}"
            audio_size = os.path.getsize(article["local_file"])  # Use the local file path to get the size
            fe.enclosure(mp3_file_url, str(audio_size), "audio/mpeg")

        if "mp3_key" in article:
            remote_file = article["mp3_key"]
            mp3_file_url = f"https://storage.googleapis.com/{bucket_name}/{remote_file}"
            fe.enclosure(mp3_file_url, 0, "audio/mpeg")

        if "published" in article:
            fe.published(article["published"])

        if "description" in article:
            fe.description(article["description"])
        else:
            fe.description("No description available.")

        fe.link(href=article["url"], rel="alternate")

    output_dir = config['podcast_feed']['output_dir']
    print(f"Output directory: {output_dir}")  # Add this line
    os.makedirs(output_dir, exist_ok=True)

    return fg.rss_str(pretty=True)


def read_urls_from_file(file_path):
    with open(file_path, "r") as f:
        urls = [line.strip() for line in f.readlines()]
    return urls

def upload_podcast_feed(bucket_name, feed_data):
    client = storage.Client()
    bucket = client.get_bucket(bucket_name)
    blob = bucket.blob("podcast_feed.xml")
    blob.upload_from_string(feed_data, content_type="application/rss+xml")
    return f"https://storage.googleapis.com/{bucket_name}/podcast_feed.xml"

def main():
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "C:/keys/gnarrate-7ab738b98a38.json"

    print("Welcome to the Article to Podcast converter!")
    input_type = input("Enter 'f' for a file or 'u' for URLs (f/u): ").strip().lower()

    if input_type == "f":
        file_path = input("Enter the path to the text file containing URLs: ").strip()
        urls = read_urls_from_file(file_path)
    elif input_type == "u":
        urls = input("Enter multiple URLs separated by commas: ").strip().split(",")
    else:
        print("Invalid input. Exiting.")
        sys.exit(1)

    print("\nExtracting articles...")
    articles = extract_articles(tqdm(urls, desc="Extracting", unit="article"))
    print("Articles extracted successfully.")

    os.makedirs("output", exist_ok=True)

    log_file = "processing_log.csv"
    bucket_name = config["google_cloud"]["bucket_name"]

    existing_podcast_feed = get_existing_podcast_feed(bucket_name)
    if existing_podcast_feed:
        print("Found an existing podcast feed.")
    else:
        print("No existing podcast feed found.")

    for i, article in enumerate(tqdm(articles, desc="Processing", unit="article")):
        log_entry_data = {
            "date_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "url": article["url"],
            "word_count": len(article["content"].split()),
            "audio_length": 0,
            "audio_filename": "",
            "status": "success",
        }
        article["audio_url"] = ""

        try:
            print(f"\nProcessing article {i + 1} of {len(articles)}:")
            print(f"Title: {article['title']}")
            output_file = f"output/article_{i + 1}_{datetime.now().strftime('%Y%m%d-%H%M%S')}.mp3"
            print("Converting text to speech...")
            text_to_speech(article['content'], output_file)
            print("Text to speech conversion completed.")

            # Save the audio length and filename to the log entry data
            audio_file = eyed3.load(output_file)
            log_entry_data["audio_length"] = audio_file.info.time_secs
            log_entry_data["audio_filename"] = output_file

            bucket_name = config["google_cloud"]["bucket_name"]
            remote_file = f"article_{i + 1}_{datetime.now().strftime('%Y%m%d-%H%M%S')}.mp3"
            print("Uploading audio file to Google Cloud Storage...")
            upload_to_bucket(bucket_name, output_file, remote_file)
            print("Audio file uploaded successfully.")
            audio_url = f"https://storage.googleapis.com/{bucket_name}/{remote_file}"
            article["local_file"] = output_file  # Add the local file path to the article dictionary
            article["remote_file"] = remote_file
            article["audio_url"] = audio_url

        except Exception as e:
            print(f"Error processing article {i + 1}: {e}")
            log_entry_data["status"] = "failed"

        # Log the entry
        log_entry(log_file, log_entry_data)

    print("\nGenerating podcast feed...")
    podcast_feed = create_podcast_feed(bucket_name, articles, config, existing_podcast_feed)
    with open("output/podcast_feed.xml", "w", encoding="utf-8") as f:
        f.write(podcast_feed.decode('utf-8'))
    print("Podcast feed generated successfully.")
    print("\nUploading podcast feed to Google Cloud Storage...")
    feed_url = upload_podcast_feed(bucket_name, podcast_feed)
    print("Podcast feed uploaded successfully.")
    print("The podcast feed is available at: output/podcast_feed.xml")

if __name__ == "__main__":
    main()