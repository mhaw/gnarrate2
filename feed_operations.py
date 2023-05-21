#feed_operations.py
import logging
from feedgen.feed import FeedGenerator
from datetime import datetime, timezone
from file_operations import get_file_size

def add_existing_entries(feed_generator, existing_feed, bucket_name):
    for entry in existing_feed.entries:
        fe = feed_generator.add_entry()
        update_entry(fe, entry, bucket_name)

def set_feed_metadata_from_existing(fg, existing_feed, config):
    fg.id(getattr(existing_feed.feed, 'id', ''))
    fg.title(getattr(existing_feed.feed, 'title', ''))
    fg.author({"name": getattr(existing_feed.feed, 'author', ''), "email": getattr(existing_feed.feed, 'email', '')})
    fg.link(href=getattr(existing_feed.feed, 'link', ''), rel="alternate")
    fg.link(href=config["podcast_feed"]["feed_url"], rel="self")
    fg.subtitle(getattr(existing_feed.feed, 'subtitle', ''))
    fg.language(getattr(existing_feed.feed, 'language', ''))
    return fg

def create_feed_entry_from_article(article, bucket_name):
    fe = FeedGenerator().add_entry()
    update_entry(fe, article, bucket_name)
    return fe

def update_entry(fe, entry, bucket_name):
    fe.id(getattr(entry, 'id', ''))
    
    title = getattr(entry, 'title', None)
    if not title:
        raise ValueError("Entry has no title")
    fe.title(title)
    
    fe.description(getattr(entry, 'description', 'No description available.'))

    link = getattr(entry, 'link', None)
    if not link:
        raise ValueError("Entry has no link")
    fe.link(href=link, rel="alternate")

    fe.published(getattr(entry, 'published', datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')))
    if hasattr(entry, 'updated'):
        fe.updated(entry.updated)
    add_enclosure(fe, entry, bucket_name)

def add_enclosure(fe, entry, bucket_name):
    try:
        mp3_file_url = getattr(entry, 'mp3_file_url', '')

        # Log the mp3_file_url
        logging.info(f"Adding enclosure for entry with id {entry.id}. URL: {mp3_file_url}")

        if entry.enclosures:
            file_name = entry.enclosures[0].href.split('/')[-1]
            file_size = get_file_size(bucket_name, file_name)
        else:
            file_size = 0

        # Add the enclosure to the feed entry
        fe.enclosure(mp3_file_url, str(file_size), "audio/mpeg")

        # Log success
        logging.info(f"Successfully added enclosure for entry with id {entry.id}")

    except Exception as e:
        logging.error(f"Failed to add enclosure for the entry with id {entry.id}: {e}")
        raise

def article_exists_in_feed(article, existing_feed_entries):
    return any(entry.link == article["url"] for entry in existing_feed_entries)
