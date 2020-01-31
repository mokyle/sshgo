#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import re
import curses
import traceback
import locale
import math
import pexpect
import struct
import fcntl
import termios
import signal
import json
import argparse
from collections import OrderedDict
from optparse import OptionParser

sshHosts = sys.path[0] + "/ssh_hosts.json"  # ssh登录信息保存在同目录的.ssh_hosts.json文件中


class SSHGO:
    UP = -1
    DOWN = 1

    KEY_O = 79
    KEY_R = 82
    KEY_G = 71
    KEY_o = 111
    KEY_r = 114
    KEY_g = 103
    KEY_c = 99
    KEY_C = 67
    KEY_m = 109
    KEY_M = 77
    KEY_d = 0x64
    KEY_u = 0x75
    KEY_SPACE = 32
    KEY_ENTER = 10
    KEY_q = 113
    KEY_ESC = 27

    KEY_j = 106
    KEY_k = 107

    KEY_SPLASH = 47
    KEY_LEFT = 260
    KEY_RIGHT = 261
    KEY_PGUP = 339
    KEY_LESS = 45  # -
    KEY_PGDOWN = 338
    KEY_EQUAL = 61  # =

    screen = None
    child = None
    scroll_bar = None
    top_right = None   # 也用于右侧scroll bar
    bottom_right = None   # 也用于右侧scroll bar
    search_keyword = None
    line_number = 0
    config = None
    host_title_list = set()
    pre_host_list = set()

    def __init__(self, config_file):

        self._parse_config_file(config_file)

        self.screen = curses.initscr()
        curses.noecho()
        curses.cbreak()
        curses.curs_set(0)
        self.screen.keypad(1)
        self.screen.border(0)

        self.top_line_number = 0
        self.highlight_line_number = 0

        curses.start_color()
        curses.use_default_colors()

        # highlight
        curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_BLUE)
        self.COLOR_HIGHLIGHT = 2
        # red
        curses.init_pair(3, curses.COLOR_RED, -1)
        self.COLOR_RED = 3

        # red highlight
        curses.init_pair(4, curses.COLOR_RED, curses.COLOR_BLUE)
        self.COLOR_RED_HIGH = 4

        # white bg
        curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_WHITE)
        self.COLOR_WBG = 5

        # black bg
        curses.init_pair(6, curses.COLOR_BLACK, curses.COLOR_BLACK)
        self.COLOR_BBG = 6

        self.run()

    def run(self):
        try:
            while True:
                self.render_screen()
                c = self.screen.getch()
                if c == curses.KEY_UP or c == self.KEY_k:
                    self.updown(-1)
                elif c == curses.KEY_DOWN or c == self.KEY_j:
                    self.updown(1)
                elif c == self.KEY_u:  # 上翻页
                    for i in range(0, curses.tigetnum('lines')):
                        self.updown(-1)
                elif c == self.KEY_d:  # 下翻页
                    for i in range(0, curses.tigetnum('lines')):
                        self.updown(1)
                elif c == self.KEY_ENTER or c == self.KEY_SPACE or c == self.KEY_RIGHT:
                    self.toggle_node()
                elif c == self.KEY_ESC or c == self.KEY_q:
                    self.exit()
                elif c == self.KEY_O or c == self.KEY_M:
                    self.open_all()
                elif c == self.KEY_o or c == self.KEY_m:
                    self.open_node()
                elif c == self.KEY_C or c == self.KEY_R:
                    self.close_all()
                elif c == self.KEY_c or c == self.KEY_r or c == self.KEY_LEFT:
                    self.close_node()
                elif c == self.KEY_PGUP or c == self.KEY_LESS:
                    self.pre_node()
                elif c == self.KEY_PGDOWN or c == self.KEY_EQUAL:
                    self.next_node()
                elif c == self.KEY_g:
                    self.page_top()
                elif c == self.KEY_G:
                    self.page_bottom()
                elif c == self.KEY_SPLASH:
                    self.enter_search_mode()
        except SystemExit:
            pass
        except:
            self.screen.keypad(0)
            self.restore_screen()
            traceback.print_exc()   # 使用curses情况下异常堆栈跟踪

    def _parse_config_file(self, config_file):

        f = open(config_file, 'r')
        text = f.read()
        f.close()
        self.config = json.loads(text)

        # 开始解析json配置文件:
        self.handle_node(None, self.config, 0)

        # 检查配置文件是否正常
        not_found_pre_host_list = self.pre_host_list - self.host_title_list
        if len(not_found_pre_host_list):
            print('\033[1;31;40m pre_host %s not found!\033[0m' % not_found_pre_host_list)
            sys.exit(1)

    def handle_node(self, parent, nodes, level):
        for anode in nodes:
            # 检查配置文件是否正常
            if anode['title'] in self.host_title_list:
                print('\033[1;31;40m title"%s"repeated in config file!\033[0m' % (anode['title']))
                sys.exit(1)
            if 'ssh' not in anode and 'pre_host' not in anode and 'sub_node' not in anode:
                print('\033[1;31;40m'
                      'Node "%s" must contains field "ssh" or "pre_host" or "sub_node" in config file!\033[0m'
                      % (anode['title']))
                sys.exit(1)

            self.host_title_list.add(anode['title'])
            self.line_number += 1
            if 'sub_node' not in anode:
                anode['sub_node'] = []
            if 'expanded' not in anode:
                anode['expanded'] = False
            if 'pre_host' in anode:
                self.pre_host_list.add(anode['pre_host'])
            if 'expect' not in anode:
                anode['expect'] = []
            anode['parent'] = parent
            anode['level'] = level
            anode['line_number'] = self.line_number
            if len(anode['sub_node']):
                self.handle_node(anode, anode['sub_node'], level + 1)

    # zssh 远程登录
    def do_ssh(self, node):
        expect_list = []
        begin_node = node
        while 'pre_host' in begin_node:
            expect_list = begin_node['expect'] + expect_list
            pre_node_title = begin_node['pre_host']
            stack = self.config + []
            while len(stack):
                anode = stack.pop()
                if anode['title'] == pre_node_title:
                    begin_node = anode
                    break
                if len(anode['sub_node']):
                    stack = stack + anode['sub_node']
        expect_list = begin_node['expect'] + expect_list
        # 删除重复的setTitle,ps1等只保留最后一个
        expect_repeat_flag = {'setTitle': False, 'ps1': False}
        for i in range(len(expect_list) - 1, -1, -1):
            for key in expect_list[i]:
                if key in expect_repeat_flag:
                    if not expect_repeat_flag[key]:
                        expect_repeat_flag[key] = True
                    else:
                        del expect_list[i]
                break  # 每个expect应只有一个键值对,多余的忽略掉.

        ssh_param = begin_node['ssh']
        ssh = 'ssh'
        if os.popen('which zssh 2> /dev/null').read().strip() != '':
            ssh = 'zssh'
        self.child = pexpect.spawn(ssh + ' ' + ssh_param, encoding='utf-8')
        self.sigwinch_passthrough()
        signal.signal(signal.SIGINT, exit)  # 捕获Ctrl+C信号
        signal.signal(signal.SIGTERM, exit)  # 捕获Ctrl+C信号
        signal.signal(signal.SIGWINCH, self.sigwinch_passthrough_with_param)  # 捕获窗口大小调整信号
        self.child.logfile_read = sys.stdout  # 只将从远端读到的内容打印到屏幕
        if len(expect_list):
            for expect in expect_list:
                for key in expect:
                    if key == 'passwd':
                        while True:
                            i = self.child.expect([pexpect.EOF, pexpect.TIMEOUT,
                                                   r'Are you sure you want to continue connecting \(yes/no',
                                                   '[Pp]assword: ', '密码：', '[$#] '], timeout=-1)
                            if i == 0:  # Exception
                                input('\033[1;31;40mException occur and will exit!\033[0m')
                                sys.exit(1)
                            elif i == 1:  # Timeout
                                input('\033[1;31;40mTimeout !\033[0m')
                                sys.exit(1)
                            elif i == 2:  # SSH does not have the public key. Just accept it.
                                self.child.sendline('yes')
                            elif i == 5:  # 用于提供了密码但是实际不需要输入密码就进去了的情况
                                self.child.sendline(
                                    '')  # 走到这里表示已经匹配了一次[$#]。配置文件中可能有下一步也是匹配[$#]的,故需要让流再次输出一次关键字$或#供下次匹配。
                                break
                            elif i == 3 or i == 4:
                                self.child.sendline(expect[key])
                                break
                    elif key == 'ps1' or key == 'ps1-bench' or key == 'ps1-prod':
                        self._make_sure_enter_bash()
                        if key == 'ps1-prod':
                            self.child.sendline("export PS1='\\[\\e[30;43m\\]" + expect[
                                key] + ":\\w\\[\\e[33;45m\\]▶\\[\\e[37;45m\\]\\t \\$\\[\\e[0m\\]\\[\\e[35m\\]▶\\[\\e[0m\\]'")
                        elif key == 'ps1-bench':
                            self.child.sendline("export PS1='\\[\\e[30;42m\\]" + expect[
                                key] + ":\\w\\[\\e[32;43m\\]▶\\[\\e[30;43m\\]\\t \\$\\[\\e[0m\\]\\[\\e[33m\\]▶\\[\\e[0m\\]'")
                        else:  # key == 'ps1'
                            self.child.sendline("export PS1='\\[\\e[30;46m\\]" + expect[
                                key] + ":\\w\\[\\e[36;42m\\]▶\\[\\e[30;42m\\]\\t \\$\\[\\e[0m\\]\\[\\e[32m\\]▶\\[\\e[0m\\]'")
                    elif key == 'setTitle':
                        self._make_sure_enter_bash()
                        title = expect[key] if expect[key] != '' else node['title']
                        self.child.sendline("PROMPT_COMMAND='echo -ne \"\\033]0;" + title + "\\007\"'")  # 设置本地终端的标题
                    else:
                        # i = self.child.expect([pexpect.TIMEOUT, key],timeout=10)
                        while True:
                            i = self.child.expect_exact([pexpect.TIMEOUT,
                                                         r'Are you sure you want to continue connecting (yes/no)?',
                                                         key],
                                                        timeout=-1)
                            if i == 2:
                                self.child.sendline(expect[key])
                                break
                            elif i == 1:  # SSH does not have the public key or key error. Just accept it.
                                self.child.sendline('yes')
                            elif i == 0:  # Timeout
                                input('\033[1;31;40mTimeout! Cannot capture string "%s".\033[0m' % key)
                                sys.exit(1)
        self.child.logfile_read = None
        self.child.interact()
        curses.cbreak()  # cbreak模式：除delete,ctrl等控制键外，其他的输入字符被立即读取
        if self.search_keyword is not None:
            self.search_keyword = None  # 退出远程连接返回到本程序后退出搜索模式

    def _get_visible_lines_for_render(self):
        lines = []
        stack = self.config + []
        while len(stack):
            node = stack.pop()
            lines.append(node)
            if 'expanded' in node and node['expanded'] and len(node['sub_node']):
                stack = stack + node['sub_node']

        lines.sort(key=lambda n: n['line_number'], reverse=False)
        return lines

    def _make_sure_enter_bash(self):
        while True:  # 设置本地终端标题 和 设置PS1 前需要确保已经进入了bash
            i = self.child.expect(
                [pexpect.TIMEOUT, '[$#]', r'Are you sure you want to continue connecting \(yes/no\)\?'])
            if i == 0:  # Timeout
                print('\033[1;31;40mTimeout!\033[0m')
                sys.exit(1)
            elif i == 1:
                break
            elif i == 2:  # SSH does not have the public key or key error. Just accept it.
                self.child.sendline('yes')

    def exit(self):
        if self.search_keyword is not None:
            self.search_keyword = None
        else:
            sys.exit(0)

    def enter_search_mode(self):
        screen_cols = curses.tigetnum('cols')
        self.screen.addstr(0, 0, '/' + ' ' * screen_cols)
        curses.echo()
        curses.curs_set(1)
        self.search_keyword = self.screen.getstr(0, 1)  # 获取输入的要搜索的内容
        curses.noecho()
        curses.curs_set(0)

    def _search_node(self):
        rt = []
        stack = self.config + []
        while len(stack):
            node = stack.pop()
            if (not len(node['sub_node'])) and re.match(self.search_keyword.decode(), (node['title'])) is not None:
                rt.append(node)
            if len(node['sub_node']):
                stack = stack + node['sub_node']
        return rt

    def get_lines(self):
        if self.search_keyword is not None:
            return self._search_node()
        else:
            return self._get_visible_lines_for_render()

    def page_top(self):
        self.top_line_number = 0
        self.highlight_line_number = 0

    def page_bottom(self):
        screen_lines = curses.tigetnum('lines')
        visible_hosts = self.get_lines()
        self.top_line_number = max(len(visible_hosts) - screen_lines, 0)
        self.highlight_line_number = min(screen_lines, len(visible_hosts)) - 1

    def open_node(self):
        visible_hosts = self.get_lines()
        line_num = self.top_line_number + self.highlight_line_number
        node = visible_hosts[line_num]
        if not len(node['sub_node']):
            return
        stack = [node]
        while len(stack):
            node = stack.pop()
            node['expanded'] = True  # 这是关键
            if len(node['sub_node']):
                stack = stack + node['sub_node']

    def close_node(self):
        visible_hosts = self.get_lines()
        line_num = self.top_line_number + self.highlight_line_number
        node = visible_hosts[line_num]
        if not len(node['sub_node']):  # 如果当前不在node上，那么移动到node上后折叠node。
            parent_node = node['parent']
            increment = node['line_number'] - parent_node['line_number']
            for i in range(0, increment):
                self.updown(-1)
            self.close_node()
            return
        stack = [node]
        while len(stack):
            node = stack.pop()
            node['expanded'] = False
            if len(node['sub_node']):
                stack = stack + node['sub_node']

    def pre_node(self):  # 关闭当前组，切换到上一组的最后一个
        self.close_node()
        self.updown(-1)
        visible_hosts = self.get_lines()
        line_num = self.top_line_number + self.highlight_line_number
        node = visible_hosts[line_num]
        if len(node['sub_node']):
            self.open_node()
            for i in range(0, len(node['sub_node'])):
                self.updown(1)

    def next_node(self):  # 关闭当前组，切换到下一组的第一个
        self.close_node()
        self.updown(1)
        self.open_node()
        self.updown(1)

    def open_all(self):
        stack = self.config + []
        while len(stack):
            node = stack.pop()
            if len(node['sub_node']):
                node['expanded'] = True
                stack = stack + node['sub_node']

    def close_all(self):
        stack = self.config + []
        while len(stack):
            node = stack.pop()
            if len(node['sub_node']):
                node['expanded'] = False
                stack = stack + node['sub_node']

    def toggle_node(self):
        visible_hosts = self.get_lines()
        line_num = self.top_line_number + self.highlight_line_number
        if not len(visible_hosts) and self.search_keyword is not None:
            self.search_keyword = None  # 退出搜索模式
            return
        node = visible_hosts[line_num]
        if len(node['sub_node']):
            node['expanded'] = not node['expanded']
        else:
            self.restore_screen()
            self.do_ssh(node)

    def render_screen(self):
        # clear screen
        self.screen.clear()

        # now paint the rows
        screen_lines = curses.tigetnum('lines')
        screen_cols = curses.tigetnum('cols')

        if self.highlight_line_number >= screen_lines:
            self.highlight_line_number = screen_lines - 1

        all_nodes = self.get_lines()
        if self.top_line_number >= len(all_nodes):
            self.top_line_number = 0

        top = self.top_line_number
        bottom = self.top_line_number + screen_lines
        nodes = all_nodes[top:bottom]

        if not len(nodes):
            self.screen.refresh()
            return

        if self.highlight_line_number >= len(nodes):
            self.highlight_line_number = len(nodes) - 1

        if self.top_line_number >= len(all_nodes):
            self.top_line_number = 0

        for (index, node,) in enumerate(nodes):
            # line_num = self.top_line_number + index

            line = node['title']
            if len(node['sub_node']):
                line += '(%d)' % len(node['sub_node'])

            prefix = ''
            if self.search_keyword is None:
                prefix += '  ' * node['level']
            if len(node['sub_node']):
                if node['expanded']:
                    prefix += '-'
                else:
                    prefix += '+'
            else:
                prefix += '|'
            prefix += ' '

            # highlight current line
            if index != self.highlight_line_number:
                self.screen.addstr(index, 0, prefix, curses.color_pair(self.COLOR_RED))
                self.screen.addstr(index, len(prefix), line)
            else:
                self.screen.addstr(index, 0, prefix, curses.color_pair(self.COLOR_RED_HIGH))
                self.screen.addstr(index, len(prefix), line, curses.color_pair(self.COLOR_HIGHLIGHT))

        # draw scroll bar
        if self.scroll_bar is None:
            self.scroll_bar = self.screen.subwin(screen_lines - 2, 1, 1, screen_cols - 1)
        self.scroll_bar.border(*(['|'] * 8))
        self.scroll_bar.noutrefresh()
        self.screen.noutrefresh()
        curses.doupdate()
        # draw right top point, why see https://stackoverflow.com/a/53757902
        if self.top_right is None:
            self.top_right = self.screen.subwin(1, 1, 0, screen_cols - 1)
        self.top_right.border(*(['^'] * 8))
        self.top_right.noutrefresh()
        self.screen.noutrefresh()
        curses.doupdate()
        # draw right bottom point
        if self.bottom_right is None:
            self.bottom_right = self.screen.subwin(1, 1, screen_lines - 1, screen_cols - 1)
        self.bottom_right.border(*(['v'] * 8))
        self.bottom_right.noutrefresh()
        self.screen.noutrefresh()
        curses.doupdate()

        scroll_top = int(math.ceil((self.top_line_number + 1.0) / max(len(all_nodes), screen_lines) * screen_lines - 1))
        scroll_height = int(math.ceil((len(nodes) + 0.0) / len(all_nodes) * screen_lines))
        highlight_pos = int(
            math.ceil(scroll_height * ((self.highlight_line_number + 1.0) / min(screen_lines, len(nodes)))))
        self.screen.insstr(min(screen_lines, scroll_top + highlight_pos) - 1, screen_cols - 1, '+',
                           curses.color_pair(self.COLOR_RED))
        self.screen.refresh()

    # move highlight up/down one line
    def updown(self, increment):
        visible_hosts = self.get_lines()
        visible_lines_count = len(visible_hosts)
        next_line_number = self.highlight_line_number + increment

        # paging
        if increment < 0 and self.highlight_line_number == 0 and self.top_line_number != 0:
            self.top_line_number += self.UP
            return
        elif increment > 0 and next_line_number == curses.tigetnum('lines') and (
                self.top_line_number + curses.tigetnum('lines')) != visible_lines_count:
            self.top_line_number += self.DOWN
            return

        # scroll highlight line
        if increment < 0 and (self.top_line_number != 0 or self.highlight_line_number != 0):
            self.highlight_line_number = next_line_number
        elif increment > 0 and (
                self.top_line_number + self.highlight_line_number + 1) != visible_lines_count \
                and self.highlight_line_number != curses.tigetnum('lines'):
            self.highlight_line_number = next_line_number

    # catch any weird termination situations
    def __del__(self):
        self.restore_screen()

    # 用于pexpect设置屏幕大小，防止vim只显示半屏
    def sigwinch_passthrough(self):
        s = struct.pack("HHHH", 0, 0, 0, 0)
        a = struct.unpack('hhhh', fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, s))
        if not self.child.closed:
            self.child.setwinsize(a[0], a[1])

    def sigwinch_passthrough_with_param(self, sig, data):
        self.sigwinch_passthrough()

    def restore_screen(self):
        curses.initscr()
        # nocbreak模式：字符先缓存，再输出
        curses.nocbreak()
        curses.echo()
        curses.endwin()


if __name__ == '__main__':
    parser = OptionParser()
    parser.add_option('-c', '--config', help='use specified config file instead of ~/.ssh_hosts')
    options, args = parser.parse_args(sys.argv)
    host_file = os.path.expanduser(sshHosts)

    if options.config is not None:
        host_file = options.config
    if not os.path.exists(host_file):
        print(sys.stderr, sshHosts, ' is not found, create it')
        fp = open(host_file, 'w')
        fp.close()

    SSHGO(host_file)
