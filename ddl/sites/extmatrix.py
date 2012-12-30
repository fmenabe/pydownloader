# -*- coding: utf-8 -*-

import os.path as path
import urllib
import urllib2
import cookielib
import string
import re
from unix import Local
import ddl

# Urls.
URL = 'http://www.extmatrix.com'
LOGIN_URL = '%s/login.php' % URL
LOGOUT_URL = '%s/logout.php' % URL
FILES_URL = '%s/members/myfiles.php' % URL

# Regex for getting captcha image.
CAPTCHA_REGEXP = re.compile('img src="./(captcha.php\?c=[0-9]*)"')
LINK_REGEXP = re.compile(r"""<a id='jd_support' href="(.*)"></a>""")

# Command of the Optical Recognition Character program.
OCR_CMD = 'gocr {file} -C "{choices}"'


class Extmatrix():
    def __init__(self):
        self.opener = urllib2.build_opener(
#            urllib2.HTTPCookieProcessor(cookielib.LWPCookieJar(cookie))
            urllib2.HTTPCookieProcessor(cookielib.CookieJar())
        )


    def __captcha(self):
        captcha = ''
        tmp_file = '/tmp/captcha.png'
        while not re.match('\d{6}', captcha):
            response = self.opener.open(LOGIN_URL)
            captcha_url = path.join(
                URL,
                CAPTCHA_REGEXP.search(response.read()).group(1)
            )
            response = self.opener.open(captcha_url)
            with open(tmp_file, 'wb') as fhandler:
                fhandler.write(response.read())

            status, stdout, stderr = Local().execute(
                OCR_CMD.format(file=tmp_file, choices=string.digits)
            )
            if not status:
                raise ddl.DownloadError("unable to resolve captcha: %s" % stderr)

            captcha = stdout.strip()

        return captcha


    def login(self, login, password):
        # Load login page for getting captcha image.
        captcha = self.__captcha()

        # Log in.
        response = self.opener.open(LOGIN_URL, urllib.urlencode({
            'user': login,
            'pass': password,
            'captcha': captcha,
            'submit': 'Login',
            'task': 'dologin',
        }))

        # Check we are logged in.
        response = self.opener.open(FILES_URL)
        if 'You must be logged in to do that' in response.read():
            raise ddl.DownloadError("unable to login")


    def logout(self):
        self.opener.open(LOGOUT_URL)


    def get_link(self, link):
        response = self.opener.open(link)

        try:
            return LINK_REGEXP.search(response.read()).group(1)
        except AttributeError:
            raise ddl.DownloadError("unable to get file link")
