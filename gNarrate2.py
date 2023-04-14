# Standard library imports
import os
import sys
import time
import json
import csv
from io import BytesIO
from pathlib import Path
from xml.etree.ElementTree import fromstring
import datetime
from datetime import datetime, timezone
import random
import re

# Third-party imports
import requests
from newspaper import Article
from google.cloud import texttospeech, storage
from feedgen.feed import FeedGenerator
from tqdm import tqdm
import math
from pydub import AudioSegment
import eyed3
import feedparser

# Application-specific imports
# (None in this case)

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

def construct_narration_text(article):
    text = f"Title: {article['title']}. "
    if "author" in article and "publication" in article:
        text += f"Written by {article['author']} for {article['publication']}. "
    elif "author" in article:
        text += f"Written by {article['author']}. "
    elif "publication" in article:
        text += f"From {article['publication']}. "
    text += article['content']
    return text

def select_natural_voice(client):
    voices = client.list_voices().voices
    natural_voices = [voice for voice in voices if any(language_code.startswith("en-") for language_code in voice.language_codes)]
    selected_voice = random.choice(natural_voices)

    # Convert the selected voice to a VoiceSelectionParams object
    voice_params = texttospeech.VoiceSelectionParams(
        language_code=selected_voice.language_codes[0],
        ssml_gender=selected_voice.ssml_gender
    )

    return voice_params

def split_text_by_sentence(text, max_chunk_size=4500):
    sentences = re.split('(?<=[.!?]) +', text)
    chunks = []
    current_chunk = ""
    for sentence in sentences:
        if len(current_chunk) + len(sentence) > max_chunk_size:
            chunks.append(current_chunk)
            current_chunk = sentence
        else:
            current_chunk += " " + sentence
    chunks.append(current_chunk)
    return chunks

def text_to_speech(article, output_file):
    client = texttospeech.TextToSpeechClient()

    # Construct the text for narration
    text = construct_narration_text(article)

    # Split text into chunks
    max_chunk_size = 4500
    chunks = split_text_by_sentence(text)

    audio_segments = []

    # Randomly select voice settings for the whole article
    speaking_rate = random.uniform(0.9, 1.1)  # Adjust this range for a more natural listening experience
    pitch = random.uniform(-2.0, 2.0)  # Adjust the pitch for a more natural voice

    voice_params = select_natural_voice(client)
    
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=speaking_rate,
        pitch=pitch
    )

    for chunk in chunks:
        input_text = texttospeech.SynthesisInput(text=chunk)

        response = client.synthesize_speech(
            input=input_text, voice=voice_params, audio_config=audio_config
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

def add_existing_entries(feed_generator, existing_feed, bucket_name):
    for entry in existing_feed.entries:
        fe = feed_generator.add_entry()
        fe.id(entry.id)
        fe.title(entry.title)
        fe.description(entry.description)
        fe.link(href=entry.link)
        if hasattr(entry, 'published'):
            fe.published(entry.published)
        if hasattr(entry, 'updated'):
            fe.updated(entry.updated)
        if entry.enclosures and len(entry.enclosures) > 0:
            file_size = get_file_size(bucket_name, entry.enclosures[0].href.split('/')[-1])
            fe.enclosure(entry.enclosures[0].href, str(file_size), "audio/mpeg")

def get_file_size(bucket_name, blob_name):
    storage_client = storage.Client()
    bucket = storage_client.get_bucket(bucket_name)
    blob = storage.Blob(blob_name, bucket)
    blob.reload()
    return blob.size

def create_podcast_feed(bucket_name, articles, config, existing_podcast_feed):
    fg = FeedGenerator()

    if existing_podcast_feed:
        existing_feed = feedparser.parse(existing_podcast_feed)
        fg = set_feed_metadata_from_existing(fg, existing_feed)
        if existing_feed:
            add_existing_entries(fg, existing_feed, bucket_name)
    else:
        fg.id(config["podcast_feed"]["feed_url"])
        fg.language(config["podcast_feed"]["language"])
        # Set other feed metadata as needed

    for article in articles:
        fe = create_feed_entry_from_article(article, bucket_name)
        fg.add_entry(fe)

    output_dir = config['podcast_feed']['output_dir']
    print(f"Output directory: {output_dir}")
    os.makedirs(output_dir, exist_ok=True)

    return fg.rss_str(pretty=True)

def set_feed_metadata_from_existing(fg, existing_feed):
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
    return fg

def create_feed_entry_from_article(article, bucket_name):
    fe = FeedGenerator().add_entry()
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
    return fe

def read_urls_from_file(file_path):
    with open(file_path, "r") as f:
        urls = [line.strip() for line in f.readlines()]
    return urls

def read_cache(file_path):
    with open(file_path, "r") as f:
        return [line.strip() for line in f.readlines()]

def update_cache(file_path, url):
    with open(file_path, "a") as f:
        f.write(url + "\n")

def upload_podcast_feed(bucket_name, feed_data):
    client = storage.Client()
    bucket = client.get_bucket(bucket_name)
    blob = bucket.blob("podcast_feed.xml")
    blob.upload_from_string(feed_data, content_type="application/rss+xml")
    return f"https://storage.googleapis.com/{bucket_name}/podcast_feed.xml"

def process_article(article, bucket_name, config):
    log_file = "processing_log.csv"
    cache_file = "processed_urls_cache.txt"
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
        output_file = f"output/article_{datetime.now().strftime('%Y%m%d-%H%M%S')}.mp3"
        print("Converting text to speech...")
        text_to_speech(article, output_file)
        print("Text to speech conversion completed.")

        # Save the audio length and filename to the log entry data
        audio_file = eyed3.load(output_file)
        log_entry_data["audio_length"] = audio_file.info.time_secs
        log_entry_data["audio_filename"] = output_file

        remote_file = f"article_{datetime.now().strftime('%Y%m%d-%H%M%S')}.mp3"
        print("Uploading audio file to Google Cloud Storage...")
        upload_to_bucket(bucket_name, output_file, remote_file)
        print("Audio file uploaded successfully.")
        audio_url = f"https://storage.googleapis.com/{bucket_name}/{remote_file}"
        article["local_file"] = output_file  # Add the local file path to the article dictionary
        article["remote_file"] = remote_file
        article["audio_url"] = audio_url

    except Exception as e:
        print(f"Error processing article: {e}")
        log_entry_data["status"] = "failed"

    # Log the entry
    log_entry(log_file, log_entry_data)

    update_cache(cache_file, article["url"])

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
    cache_file = "processed_urls_cache.txt"
    processed_urls = read_cache(cache_file)
    urls = [url for url in urls if url not in processed_urls]
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

    print("\nProcessing articles...")
    for i, article in enumerate(articles, start=1):
        print(f"\nProcessing article {i} of {len(articles)}:")
        print(f"Title: {article['title']}")
        process_article(article, bucket_name, config)
    print("Finished processing articles.")

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