#!/usr/bin/env python

"""
Script for initialising the documentation
"""
import os
from subprocess import call

import sys
import time
from PyQt5.QtCore import QSize, QUrl
from PyQt5.QtGui import QImage, QPainter
from PyQt5.QtWebKitWidgets import QWebView
from PyQt5.QtWidgets import QApplication


path_to_doc = "documentation"
if os.getcwd().endswith("scripts"):
    path_to_doc = ".."

make_docs_cmd = "make html"
if os.name != "posix":
    # here we re-activate the virtual environment first
    make_docs_cmd = "activate a1-venv & " + make_docs_cmd


class ScreenShot(QWebView):
    def __init__(self):
        self.app = QApplication(sys.argv)
        QWebView.__init__(self)
        self._loaded = False
        self.loadFinished.connect(self.load_finished)

    def capture(self, url, output_file, width=1500, height=1000):
        self.load(QUrl(url))
        self.wait_load()
        # set to webpage size
        frame = self.page().mainFrame()
        self.page().setViewportSize(QSize(width, height))
        # render image
        time.sleep(5)
        image = QImage(self.page().viewportSize(), QImage.Format_ARGB32)
        painter = QPainter(image)
        frame.render(painter)
        painter.end()
        print("saving to ", output_file)
        image.save(output_file)

    def wait_load(self, delay=0):
        # process app events until page loaded
        while not self._loaded:
            self.app.processEvents()
            time.sleep(delay)
        self._loaded = False

    def load_finished(self, result):
        self._loaded = True


def make_screen_shots(views):

    print("Capturing screen shots ...")

    width = 1500
    height = 1500
    s = ScreenShot()
    for view in views:
        url = "http://127.0.0.1:5000/%s" % view
        print("Loading", url)
        s.capture(
            url,
            path_to_doc + "/img/screenshot_%s.png" % view,
            width=width,
            height=height,
        )
    return


def initialise_docs():
    """Initialise doc files"""

    print("Processing documentation files ...")
    call(make_docs_cmd, shell=True, cwd=path_to_doc)


if __name__ == "__main__":
    """Initialise screen shots and documentation"""
    # Todo: log in before taking screenshots

    # make_screen_shots(["dashboard", "portfolio", "control", "analytics"])
    initialise_docs()
