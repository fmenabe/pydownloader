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
from lib.scheduler import DownloadError, trying

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

@trying(max_try=10, wait=1)
def init(shared_link, cur_try=1):
    session = requests.Session()

    tmpfile = '/tmp/captcha-%s.png' % os.getpid()
    # Get captcha URL.
    shared_link.msg = 'retrieving captcha (%s)' % cur_try
    response = session.get(LOGIN_URL, timeout=10)
    if response.status_code != 200:
        raise DownloadError('%d: %s' % (response.status_code, response.text))
    captcha_url = os.path.join(_URL, _CAPTCHA_RE.search(response.text).group(1))

    # Get captcha image.
    shared_link.msg = 'writing captcha file (%s)' % cur_try
    response = session.get(captcha_url, stream=True, timeout=10)
    if response.status_code != 200:
        raise DownloadError('%d: %s' % (response.status_code, response.text))
    with open(tmpfile, 'wb') as fhandler:
        response.raw.decode_content = True
        shutil.copyfileobj(response.raw, fhandler)

    # Resolve captcha.
    shared_link.msg = 'resolving captcha (%s)' % cur_try
    time.sleep(0.5) # Wait for seeing the message in the ui!
    command = subprocess.run(
        ['gocr', '-C', string.digits, tmpfile],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if command.returncode != 0:
        raise DownloadError(command.stderr)
    captcha = command.stdout.strip()

    # Removing tmp file.
    shared_link.msg = 'removing captcha file (%s)' % cur_try
    os.remove(tmpfile)

    # Log in.
    shared_link.msg = 'logging in (%s)' % cur_try
    post = {'user': IDS['login'],
            'pass': IDS['password'],
            'captcha': captcha,
            'submit': 'Login',
            'task': 'dologin'}
    response = session.post(LOGIN_URL, data=post, timeout=10)
    if response.status_code != 200:
        raise DownloadError('%d: %s' % (response.status_code, response.text))

    # Check we are logged in.
    shared_link.msg = 'checking logged in (%s)' % cur_try
    response = session.get(FILES_URL, timeout=10)
    if _NOT_LOGGED in response.text:
        raise DownloadError('%d: %s' % (response.status_code, response.text))

    setattr(sys.modules[__name__], 'session', session)

@trying(max_try=5, wait=1)
def get_link(shared_link, cur_try):
    try:
        shared_link.msg = 'retrieving real url (%s)' % cur_try
        response = session.get(shared_link.url, timeout=10)
        if response.status_code != 200:
            raise DownloadError('%d: %s' % (response.status_code, response.text))
        regex = _LINK_RE.search(response.text)
        if regex is None:
            raise DownloadError('invalid page')
        shared_link.real_url =  regex.group(1)
    except IOError as err:
        raise DownloadError(str(err))
