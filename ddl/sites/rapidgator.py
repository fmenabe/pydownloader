# -*- coding: utf-8 -*-

import os.path as path
import urllib
import urllib2
import cookielib
import re
import ddl

# Urls.
URL = 'https://rapidgator.net'
LOGIN_URL = '%s/auth/login' % URL
LOGOUT_URL = '%s/auth/logout' % URL

ERR_MSG = 'Please fix the following input errors'

LINK_REGEXP = re.compile("var premium_download_link = '(.*)';")

class Rapidgator(object):
    def __init__(self):
        self.opener = urllib2.build_opener(
            urllib2.HTTPCookieProcessor(cookielib.CookieJar())
        )


    def login(self, login, password):
        response = self.opener.open(LOGIN_URL, urllib.urlencode({
            'LoginForm[email]': login,
            'LoginForm[password]': password
        }))
        if ERR_MSG in response.read():
            raise ddl.DownloadError("unable to login")


    def logout(self):
        self.opener.open(LOGOUT_URL)


    def get_link(self, link):
        try:
            response = self.opener.open(link)
            return LINK_REGEXP.search(response.read()).group(1)
        except urllib2.HTTPError as err:
            raise ddl.DownloadError("unable to get file link: %s" % err)
        except AttributeError:
            raise ddl.DownloadError("unable to get file link")
