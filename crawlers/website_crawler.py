import logging
import os
from usp.tree import sitemap_tree_for_homepage  # type: ignore
from ratelimiter import RateLimiter
from core.crawler import Crawler, recursive_crawl
from core.utils import clean_urls
import re

# disable USP annoying logging
logging.getLogger("usp.fetch_parse").setLevel(logging.ERROR)
logging.getLogger("usp.helpers").setLevel(logging.ERROR)



class WebsiteCrawler(Crawler):
    def crawl(self):
        base_urls = self.cfg.website_crawler.urls
        crawled_urls = set()

        if "url_regex" in self.cfg.website_crawler:
            url_regex = [re.compile(r) for r in self.cfg.website_crawler.url_regex]
            logging.info(
                f"Filtering URLs by these regular expressions: {self.cfg.website_crawler.url_regex}"
            )
        else:
            url_regex = None

        for homepage in base_urls:
            if self.cfg.website_crawler.pages_source == "sitemap":
                tree = sitemap_tree_for_homepage(homepage)
                urls = [page.url for page in tree.all_pages()]
            elif self.cfg.website_crawler.pages_source == "crawl":
                urls = recursive_crawl(homepage, self.cfg.website_crawler.max_depth, url_regex=url_regex)
                urls = clean_urls(urls)

            if url_regex:
                urls = [u for u in urls if any([r.match(u) for r in url_regex])]
            urls = list(set(urls))

            logging.info(
                f"Finished crawling using {homepage}, found {len(urls)} URLs to index"
            )

            delay = max(self.cfg.website_crawler.get("delay", 0.1), 0.1)    # seconds between requests
            rate_limiter = RateLimiter(
                max_calls=1, period=delay                                   # at most 1 call every `delay` seconds
            )
            for inx, url in enumerate(urls):
                if url in crawled_urls:
                    logging.info(
                        f"Skipping {url} since it was already crawled in this round"
                    )
                    continue

                extraction = self.cfg.website_crawler.extraction
                metadata = {"source": "website", "url": url}

                if inx % 100 == 0:
                    logging.info(f"Crawling URL number {inx} out of {len(urls)}")

                if extraction == "pdf":
                    try:
                        with rate_limiter:
                            filename = self.url_to_file(url, title=None)
                    except Exception as e:
                        logging.error(f"Error while processing {url}: {e}")
                        continue
                    try:
                        succeeded = self.indexer.index_file(
                            filename, uri=url, metadata=metadata
                        )
                        if not succeeded:
                            logging.info(
                                f"Indexing failed for {url}, deleting document from corpus, then trying to index again"
                            )
                            doc_id = url
                            self.indexer.delete_doc(doc_id)  # doc_id is the URL itself
                            self.indexer.index_file(
                                filename, uri=url, metadata=metadata
                            )
                        if os.path.exists(filename):
                            os.remove(filename)
                        crawled_urls.add(url)
                    except Exception as e:
                        import traceback

                        logging.error(
                            f"Error while indexing {url}: {e}, traceback={traceback.format_exc()}"
                        )
                else:  # use index_url which uses PlayWright
                    logging.info(f"Crawling and indexing {url}")
                    with rate_limiter:
                        succeeded = self.indexer.index_url(url, metadata=metadata)
                    if not succeeded:
                        logging.info(
                            f"Indexing failed for {url}, deleting document from corpus, then trying to index again"
                        )
                        doc_id = url
                        self.indexer.delete_doc(doc_id)  # doc_id is the URL itself
                        self.indexer.index_url(url, metadata=metadata)
                        logging.info(f"Finished deleting and reindexing page {url}")
                    crawled_urls.add(url)
                    logging.info(f"Crawled {url} successfully")
