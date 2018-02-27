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


make_docs_cmd = 'cd documentation; make html; cd ..'
if os.name != "posix":
    print(hasattr(sys, 'real_prefix'))
    make_docs_cmd = 'activate a1-venv & cd documentation & make html & cd ..'  # re-activate the virtual environment


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
        image = QImage(self.page().viewportSize(), QImage.Format_ARGB32)
        painter = QPainter(image)
        frame.render(painter)
        painter.end()
        print('saving', output_file)
        image.save(output_file)

    def wait_load(self, delay=0):
        # process app events until page loaded
        while not self._loaded:
            self.app.processEvents()
            time.sleep(delay)
        self._loaded = False

    def load_finished(self, result):
        self._loaded = True


def initialise_screen_shots(views):
    width = 1500
    height = 1500
    s = ScreenShot()
    for view in views:
        s.capture('http://127.0.0.1:5000/' + view, 'documentation/img/screenshot_' + view + '.png',
                  width=width, height=height)
    return


def initialise_docs():
    """Initialise doc files"""

    print("Processing documentation files ...")

    call(make_docs_cmd, shell=True)


if __name__ == "__main__":
    """Initialise screen shots and documentation"""

    initialise_screen_shots(['dashboard', 'portfolio', 'control', 'analytics'])
    initialise_docs()
