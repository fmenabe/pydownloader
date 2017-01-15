# coding: utf-8

import os
import urwid
#import urwid.raw_display
from lib.scheduler import SharedLink

import logging
logger = logging.getLogger('pydownloader')

PALETTE = [
    ('header',       '', '', '', 'h0',   'h245'),
    ('panel',        '', '', '', 'h1',   ''),
    ('starting',     '', '', '', 'h0',   'h15'),
    ('connecting',   '', '', '', 'h243', 'h15'),
    ('initializing', '', '', '', 'h238', 'h15'),
    ('waiting',      '', '', '', 'h17',  'h15'),
    ('downloading',  '', '', '', 'h94',  'h15'),
    ('finished',     '', '', '', 'h29',  'h15'),
    ('failed',       '', '', '', 'h88',  'h15'),
    ('keys',         '', '', '', 'h0',   'h7')]


class UI:
    def __init__(self, scheduler, version):
        self.scheduler = scheduler

        # Header.
        header = urwid.AttrMap(urwid.Text(version), 'header')

        # Footer.
        self.status = urwid.Text('- download(s) at -')
        footer = urwid.Pile([
            urwid.Columns([
                urwid.Text(''),
                ('fixed', 29, urwid.AttrMap(urwid.Text('Keys'), 'header')),
                ('fixed', 28, urwid.AttrMap(urwid.Text(''), 'header'))]),
            urwid.Columns([
                urwid.Text(''),
                ('fixed', 28,
                 urwid.AttrMap(urwid.Text('j/Down: go down'), 'keys')),
                ('fixed', 1, urwid.Text('\u2502')),
                ('fixed', 28,
                 urwid.AttrMap(urwid.Text('s:     show all real links'), 'keys'))]),
            urwid.Columns([
                urwid.Text(''),
                ('fixed', 28,
                 urwid.AttrMap(urwid.Text(['k/Up:   go up']), 'keys')),
                ('fixed', 1, urwid.Text('\u2502')),
                ('fixed', 28,
                 urwid.AttrMap(urwid.Text('h:     hide all real links'), 'keys'))]),
            urwid.Columns([
                self.status,
                ('fixed', 28,
                 urwid.AttrMap(urwid.Text('Enter:  show/hide real link'), 'keys')),
                ('fixed', 1, urwid.Text('\u2502')),
                ('fixed', 28,
                 urwid.AttrMap(urwid.Text('q/Esc: quit'), 'keys'))])])

        # Links.
        self.links = urwid.SimpleListWalker([])

        # Window.
        window = urwid.Frame(Links(self.links), header=header, footer=footer)

        # Main loop.
        self.main_loop = urwid.MainLoop(window, PALETTE, unhandled_input=self._keyevent)
        self.main_loop.screen.set_terminal_properties(colors=256)

    def _keyevent(self, key):
        if key in ('Q','q','esc'):
            self.scheduler.stop()
            raise urwid.ExitMainLoop()
        elif key in ('k', 'up'):
            line, idx = self.links.get_focus()
            link = line.link
            if idx > 0:
                self.links.set_focus(idx - 1)
        elif key in ('j', 'down'):
            line, idx = self.links.get_focus()
            link = line.link
            if idx < len(self.links) - 1:
                self.links.set_focus(idx + 1)
        elif key == 'enter':
            line, idx = self.links.get_focus()
            link = line.link
            link.show_infos = not link.show_infos
            link.set_text(link.text)
        elif key in ('s', 'S'):
            for line in self.links:
                line.link.show_infos = True
                line.link.refresh()
        elif key in ('h', 'H'):
            for line in self.links:
                line.link.show_infos = False
                line.link.refresh()

    def run(self):
        """Initialize alarms and start main loop."""
        self.refresh()
        self.download_refresh()
        self.main_loop.run()

    def refresh(self, loop=None, user_data=None):
        for idx, shared_link in enumerate(self.scheduler.shared_links):
            # Get or add link to the UI.
            try:
                item = self.links[idx]
            except IndexError:
                item = Line(SharedLink(shared_link.url, self.scheduler.shared_links))
                self.links.append(item)
            item.refresh()
        self.main_loop.set_alarm_in(.2, self.refresh)

    def download_refresh(self, loop=None, user_data=None):
        speeds = []
        for shared_link in self.scheduler.shared_links:
            if shared_link.status == 'downloading' and not shared_link.msg:
                speeds.append(shared_link.speed or 0)

        avg_speed = (sum(speeds) if speeds else 0) / 1024 / 1024
        self.status.set_text('%d download(s) at %.2f Mb/s' % (len(speeds), avg_speed))
        self.main_loop.set_alarm_in(1, self.download_refresh)


class Links(urwid.ListBox):
    def keypress(self, size, key):
        """Let the UI manage Up and Down keys."""
        return key


class Line(urwid.AttrMap):
    def __init__(self, shared_link):
        self.shared_link = shared_link
        self.link = Link(shared_link)
        self.status = urwid.Text('status', align='right')
        columns = urwid.Columns([self.link, ('fixed', 30, self.status)])
        urwid.AttrMap.__init__(self, columns, 'panel')

    def refresh(self):
        # Refresh URL.
        self.link.refresh()

       # Refresh status.
        if self.shared_link.msg and self.shared_link.status != 'failed':
            status_text = self.shared_link.msg
        elif self.shared_link.status == 'downloading':
            downloaded = (self.shared_link.downloaded or 0) / 1024 / 1024
            filesize = (self.shared_link.filesize or 0) / 1024 / 1024
            speed = (self.shared_link.speed or 0) / 1024 / 1024
            status_text = '%.1f/%.1f Mb (%.2f Mb/s)' % (downloaded, filesize, speed)
        elif self.shared_link.status == 'finished':
            downloaded = self.shared_link.downloaded / 1024 / 1024
            filesize = self.shared_link.filesize / 1024 / 1024
            status_text = '%d/%d Mb' % (downloaded, filesize)
        else:
            status_text = self.shared_link.status
        self.status.set_text((self.shared_link.status, status_text))


class Link(urwid.Text):
    _selectable = True
    focus = False
    show_infos = False

    def __init__(self, shared_link):
        self.shared_link = shared_link
        urwid.Text.__init__(self, self.text)

    @property
    def text(self):
        # Prevent errors when showing real link before the provider was initialized.
        if self.shared_link.status == 'connecting':
            self.show_infos = False
        text = ('+%s' % self.shared_link.url
                if self.shared_link.real_url and not self.show_infos
                else self.shared_link.url)
        if self.show_infos:
            text += ('\n └─%s' % self.shared_link.real_url
                     if self.shared_link.real_url
                     else '')
            text += ('\n%s' % self.shared_link.msg
                     if self.shared_link.status == 'failed'
                     else '')
        return text

    def refresh(self):
        self.set_text(self.text)

    def render(self, size, focus=False):
        self.set_text((self.shared_link.status,
                       '>%s' % self.text if focus else ' %s' % self.text))
        return urwid.Text.render(self, size, focus)
