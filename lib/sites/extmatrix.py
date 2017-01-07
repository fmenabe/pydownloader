# coding: utf-8

import os
import re
import sys
import time
import string
import shutil
import requests
import clg.conf
#from unix import Local
import subprocess
from lib.scheduler import DownloadError

import logging
logger = logging.getLogger('pydownloader')

IDS = clg.conf.EXTMATRIX

_URL = 'http://www.extmatrix.com'
LOGIN_URL = os.path.join(_URL, 'login.php')
LOGOUT_URL = os.path.join(_URL, 'logout.php')
FILES_URL = os.path.join(_URL, 'members', 'myfiles.php')

_CAPTCHA_RE = re.compile(r'img src="./(captcha.php\?c=[0-9]*)"')
_LINK_RE = re.compile(r"""<a id='jd_support' href="(.*)"></a>""")

_NOT_LOGGED = 'You must be logged in to do that'

def init(max_try=10, wait=1):
    session = requests.Session()

    tmpfile = '/tmp/captcha-%s.png' % os.getpid()
    nb_try = 1
    error = None
    while True:
        time.sleep(wait)
        if nb_try > max_try:
            raise DownloadError('unable to initialize: %s' % error)

        try:
            # Get captcha URL.
            yield('retrieving captcha (%s)' % nb_try)
            response = session.get(LOGIN_URL, timeout=10)
            if response.status_code != 200:
                nb_try += 1
                error = response.status_code
                continue
            captcha_url = os.path.join(_URL, _CAPTCHA_RE.search(response.text).group(1))

            # Get captcha image.
            yield('writing captcha file (%s)' % nb_try)
            response = session.get(captcha_url, stream=True, timeout=10)
            if response.status_code != 200:
                nb_try += 1
                error = response.status_code
                continue
            with open(tmpfile, 'wb') as fhandler:
                response.raw.decode_content = True
                shutil.copyfileobj(response.raw, fhandler)

            # Resolve captcha.
            yield('resolving captcha (%s)' % nb_try)
            time.sleep(0.5) # Wait for seeing the message in the ui!
            command = subprocess.run(
                ['gocr', '-C', string.digits, tmpfile],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if command.returncode != 0:
                raise DownloadError(command.stderr)
            captcha = command.stdout.strip()

            # Removing tmp file.
            yield('removing captcha file (%s)' % nb_try)
            os.remove(tmpfile)

            # Log in.
            yield('logging in (%s)' % nb_try)
            post = {'user': IDS['login'],
                    'pass': IDS['password'],
                    'captcha': captcha,
                    'submit': 'Login',
                    'task': 'dologin'}
            response = session.post(LOGIN_URL, data=post, timeout=10)
            if response.status_code != 200:
                nb_try += 1
                error = response.status_code
                continue

            # Check we are logged in.
            yield('checking logged in (%s)' % nb_try)
            response = session.get(FILES_URL, timeout=10)
            if _NOT_LOGGED in response.text:
                nb_try += 1
                error = response.status_code
                continue

            setattr(sys.modules[__name__], 'session', session)
            break
        except IOError as err:
            error = str(err)
            nb_try += 1

def get_link(link, max_try=10, wait=1):
    nb_try = 1
    error = None
    while True:
        time.sleep(wait)
        if nb_try > max_try:
            raise DownloadError('unable to initialize: %s' % error)

        try:
            yield('retrieving real url (%s)' % nb_try)
            response = session.get(link, timeout=10)
            if response.status_code != 200:
                nb_try += 1
                error = response.status_code
                continue
            regex = _LINK_RE.search(response.text)
            if regex is None:
                nb_try += 1
                error = 'invalid page'
                continue
            raise GeneratorExit(regex.group(1))
        except IOError as err:
            error = str(err)
            nb_try += 1
