import logging
from datetime import datetime, timezone
from feedgen.feed import FeedGenerator
from google.cloud import storage

from file_operations import get_file_size, upload_to_bucket


class PodcastFeedManager:

    def __init__(self, bucket_name, output_dir, config):
        self.bucket_name = bucket_name
        self.output_dir = output_dir
        self.config = config

    def get_existing_podcast_feed(self, prefix='podcast_feed/'):
        client = storage.Client()
        blobs = client.list_blobs(self.bucket_name, prefix=prefix)
        for blob in blobs:
            if blob.name == 'gnarrate2feed.xml':
                return blob.download_as_text()
        return None

    def create_podcast_feed(self, articles, existing_podcast_feed=None):
        fg = FeedGenerator()
        if existing_podcast_feed:
            fg.load(existing_podcast_feed, format='xml')

        fg.id(self.config['podcast_feed']['id'])
        fg.title(self.config['podcast_feed']['title'])
        fg.author({"name": self.config['podcast_feed']['author'], "email": self.config['podcast_feed']['email']})
        fg.link(href=self.config['podcast_feed']['link'], rel='alternate')
        fg.subtitle(self.config['podcast_feed']['subtitle'])
        fg.link(href=self.config['podcast_feed']['feed_url'], rel='self')
        fg.language(self.config['podcast_feed']['language'])

        for article in articles:
            fe = fg.add_entry()
            fe.id(article['url'])
            fe.title(article['title'])
            fe.description(article['description'])
            fe.link(href=article['audio_url'], rel='enclosure', type='audio/mpeg')
            fe.published(article['publish_date'].strftime('%Y-%m-%dT%H:%M:%SZ'))
            fe.updated(article['publish_date'].strftime('%Y-%m-%dT%H:%M:%SZ'))

        return fg.rss_str(pretty=True)

    def generate_and_upload_podcast_feed(self, articles):
        existing_podcast_feed = self.get_existing_podcast_feed()
        podcast_feed = self.create_podcast_feed(articles, existing_podcast_feed)

        output_file = f'{self.output_dir}/gnarrate2feed.xml'
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(podcast_feed.decode('utf-8'))

        remote_file = 'output/gnarrate2feed.xml'
        upload_to_bucket(self.bucket_name, output_file, remote_file)

        for article in articles:
            audio_url = f'https://storage.googleapis.com/{self.bucket_name}/{remote_file}'
            article.update({
                'local_file': output_file,
                'remote_file': remote_file,
                'audio_url': audio_url
            })

        return f'https://storage.googleapis.com/{self.bucket_name}/{remote_file}'
