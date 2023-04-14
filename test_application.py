import os
import gNarrate2 as main
import feedparser
import io

# Add the validate_rss_feed function
def validate_rss_feed(feed_data):
    try:
        rss = feedparser.parse(feed_data)
        return True, "The RSS feed is valid."
    except Exception as e:
        return False, f"Error: {e}"

def test_application():
    test_urls = [
        "https://www.wired.com/story/unbelievable-zombie-comeback-analog-computing/",
        "https://psyche.co/guides/how-to-forgive-yourself-and-move-past-a-hurtful-mistake?utm_source=pocket_collection_story",
        "https://www.theguardian.com/society/2023/feb/23/one-billionaire-at-a-time-swiss-clinics-super-rich-rehab-therapy-paracelsus-kusnacht?utm_source=pocket_collection_story",
    ]

    articles = main.extract_articles(test_urls)
    bucket_name = main.config["google_cloud"]["bucket_name"]
    existing_podcast_feed = main.get_existing_podcast_feed(bucket_name)
    podcast_feed = main.create_podcast_feed(bucket_name, articles, main.config, existing_podcast_feed)

    with open("test_output.xml", "w", encoding="utf-8") as f:
        f.write(podcast_feed.decode('utf-8'))

    print("Test output XML file is available at: test_output.xml")

    # Call the validate_rss_feed function to validate the generated podcast feed
    with open("test_output.xml", "r", encoding="utf-8") as f:
        xml_data = f.read()
        is_valid, validation_message = validate_rss_feed(xml_data)
        print(validation_message)

if __name__ == "__main__":
    test_application()