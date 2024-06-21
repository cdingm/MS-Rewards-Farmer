import json
import logging
import random
import shelve
import time
from datetime import date, timedelta
from enum import Enum, auto
from itertools import cycle
from typing import Final

import requests
from selenium.webdriver.common.by import By

from src.browser import Browser
from src.utils import Utils, RemainingSearches

LOAD_DATE_KEY = "loadDate"


class AttemptsStrategy(Enum):
    exponential = auto()
    constant = auto()


class Searches:
    config = Utils.loadConfig()
    maxAttempts: Final[int] = config.get("attempts", {}).get("max", 6)
    baseDelay: Final[int] = config.get("attempts", {}).get("base_delay_in_seconds", 60)
    attemptsStrategy = Final[
        AttemptsStrategy[
            config.get("attempts", {}).get("strategy", AttemptsStrategy.constant.name)
        ]
    ]

    def __init__(self, browser: Browser, searches: RemainingSearches):
        self.browser = browser
        self.webdriver = browser.webdriver

        self.googleTrendsShelf: shelve.Shelf = shelve.open("google_trends")
        logging.debug(f"google_trends = {list(self.googleTrendsShelf.items())}")
        loadDate: date | None = None
        if LOAD_DATE_KEY in self.googleTrendsShelf:
            loadDate = self.googleTrendsShelf[LOAD_DATE_KEY]

        if loadDate is None or loadDate < date.today():
            self.googleTrendsShelf.clear()
            self.googleTrendsShelf[LOAD_DATE_KEY] = date.today()
            trends = self.getGoogleTrends(searches.getTotal())
            random.shuffle(trends)
            for trend in trends:
                self.googleTrendsShelf[trend] = None
            logging.debug(
                f"google_trends after load = {list(self.googleTrendsShelf.items())}"
            )

    def getGoogleTrends(self, wordsCount: int) -> list[str]:
        # Function to retrieve Google Trends search terms
        searchTerms: list[str] = []
        i = 0
        while len(searchTerms) < wordsCount:
            i += 1
            # Fetching daily trends from Google Trends API
            r = requests.get(
                f"https://trends.google.com/trends/api/dailytrends?hl={self.browser.localeLang}"
                f'&ed={(date.today() - timedelta(days=i)).strftime("%Y%m%d")}&geo={self.browser.localeGeo}&ns=15'
            )
            trends = json.loads(r.text[6:])
            for topic in trends["default"]["trendingSearchesDays"][0][
                "trendingSearches"
            ]:
                searchTerms.append(topic["title"]["query"].lower())
                searchTerms.extend(
                    relatedTopic["query"].lower()
                    for relatedTopic in topic["relatedQueries"]
                )
            searchTerms = list(set(searchTerms))
        del searchTerms[wordsCount: (len(searchTerms) + 1)]
        return searchTerms

    def getRelatedTerms(self, word: str) -> list[str]:
        # Function to retrieve related terms from Bing API
        return requests.get(
            f"https://api.bing.com/osjson.aspx?query={word}",
            headers={"User-agent": self.browser.userAgent},
        ).json()[1]

    def bingSearches(self, numberOfSearches: int, pointsCounter: int = 0) -> int:
        # Function to perform Bing searches
        logging.info(
            f"[BING] Starting {self.browser.browserType.capitalize()} Edge Bing searches..."
        )

        self.webdriver.get("https://bing.com")

        for searchCount in range(1, numberOfSearches + 1):
            # todo - Disable cooldown for first 3 searches (Earning starts with your third search)
            logging.info(f"[BING] {searchCount}/{numberOfSearches}")
            googleTrends: list[str] = list(self.googleTrendsShelf.keys())
            logging.debug(f"self.googleTrendsShelf.keys() = {googleTrends}")
            searchTerm = list(self.googleTrendsShelf.keys())[1]
            pointsCounter = self.bingSearch(searchTerm)
            logging.debug(f"pointsCounter = {pointsCounter}")
            time.sleep(random.randint(10, 15))

        logging.info(
            f"[BING] Finished {self.browser.browserType.capitalize()} Edge Bing searches !"
        )
        self.googleTrendsShelf.close()
        return pointsCounter

    def bingSearch(self, word: str) -> int:
        # Function to perform a single Bing search
        pointsBefore = self.getAccountPoints()

        wordsCycle: cycle[str] = cycle(self.getRelatedTerms(word))
        baseDelay = Searches.baseDelay
        originalWord = word

        for i in range(self.maxAttempts):
            # self.webdriver.get("https://bing.com")
            searchbar = self.browser.utils.waitUntilClickable(By.ID, "sb_form_q")
            searchbar.clear()
            word = next(wordsCycle)
            logging.debug(f"word={word}")
            for _ in range(100):
                searchbar.send_keys(word)
                if searchbar.get_attribute("value") != word:
                    logging.debug("searchbar != word")
                    continue
                break

            assert searchbar.get_attribute("value") == word

            searchbar.submit()

            pointsAfter = self.getAccountPoints()
            if pointsBefore < pointsAfter:
                del self.googleTrendsShelf[originalWord]
                return pointsAfter

            # todo
            # if i == (maxAttempts / 2):
            #     logging.info("[BING] " + "TIMED OUT GETTING NEW PROXY")
            #     self.webdriver.proxy = self.browser.giveMeProxy()

            baseDelay += random.randint(1, 10)  # add some jitter
            logging.debug(
                f"[BING] Search attempt failed {i + 1}/{Searches.maxAttempts}, retrying after sleeping {baseDelay}"
                f" seconds..."
            )
            time.sleep(baseDelay)

            if Searches.attemptsStrategy == AttemptsStrategy.exponential:
                baseDelay *= 2
        # todo debug why we get to this point occasionally even though searches complete
        # update - Seems like account points aren't refreshing correctly see
        logging.error("[BING] Reached max search attempt retries")
        return pointsBefore

    def getAccountPoints(self) -> int:
        if self.browser.mobile:
            return self.browser.utils.getBingInfo()["userInfo"]["balance"]
        microsoftRewardsCounter = self.browser.utils.waitUntilVisible(By.ID, "id_rc")
        return int(microsoftRewardsCounter.text)
