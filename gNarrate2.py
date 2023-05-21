import logging
import os
import traceback
from datetime import datetime
from tqdm import tqdm
from article_processing import extract_articles, process_article
from file_operations import read_cache, read_urls_from_file, update_cache
from configure import load_config
from speech_gen import select_natural_voice
from podcast_feed_generation import PodcastFeedManager

config = load_config()

logging.basicConfig(level=logging.INFO)

def main():
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "C:/keys/gnarrate-7ab738b98a38.json"

    logging.info("Welcome to the Article to Podcast converter!")

    urls = []
    successfully_added_articles = []

    bucket_name = config["google_cloud"]["bucket_name"]
    output_dir = config["podcast_feed"]["output_dir"]
    feed_manager = PodcastFeedManager(bucket_name, output_dir, config)

    while True:
        print("\nChoose an option (enter one option number per line):")
        print("1. Enter URLs")
        print("2. Load URLs from a file")
        print("3. Process articles and generate podcast")
        print("4. Exit")

        option = input("Enter the option number (1-4): ").strip()

        if option == "1":
            input_urls = input("Enter multiple URLs separated by commas: ").strip().split(",")
            urls.extend(input_urls)
            logging.info("URLs added successfully.")

        elif option == "2":
            file_path = input("Enter the path to the text file containing URLs: ").strip()
            input_urls = read_urls_from_file(file_path)
            urls.extend(input_urls)
            logging.info("URLs loaded successfully.")

        elif option == "3":
            if len(urls) == 0:
                logging.info("No URLs to process. Please add URLs first.")
                continue

            logging.info("\nExtracting and processing articles...")
            cache_file = "processed_urls_cache.txt"
            processed_urls = read_cache(cache_file)
            urls_to_process = [url for url in urls if url not in processed_urls]

            os.makedirs("output", exist_ok=True)

            for url in tqdm(urls_to_process, desc="Processing", unit="article"):
                try:
                    logging.info(f"Extracting article from {url}")
                    articles = extract_articles([url])
                    if not articles:
                        logging.error(f"No articles extracted from {url}")
                        continue
                    article = articles[0]

                    logging.info(f"Processing article from {url}")
                    process_article(article, bucket_name, config, select_natural_voice)

                    if article.get("audio_url"):
                        successfully_added_articles.append(article)
                        update_cache(cache_file, article["url"])
                    else:
                        logging.error(f"Article from {url} was not successfully added to the podcast feed")
                except Exception as e:
                    logging.error(f"Error processing article at '{url}': {traceback.format_exc()}")

            logging.info("Finished processing articles.")

            if not successfully_added_articles:
                logging.info("No articles were processed successfully. Skipping podcast feed generation.")
                continue

            logging.info("\nGenerating and uploading podcast feed...")
            feed_url = feed_manager.generate_and_upload_podcast_feed(successfully_added_articles)

            if feed_url:
                logging.info("Podcast feed generated and uploaded successfully.")
                logging.info(f"The podcast feed is available at: {feed_url}")
            else:
                logging.error("Failed to generate and upload podcast feed.")

        elif option == "4":
            logging.info("Exiting...")
            break

        else:
            logging.warning("Invalid input. Please enter a valid option number (1-4).")

if __name__ == "__main__":
    main()