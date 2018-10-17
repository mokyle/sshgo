#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os,sys,re
import curses
import locale
import math
import pexpect, struct, fcntl, termios, signal
import json, argparse
from collections import OrderedDict
from optparse import OptionParser
sshHosts = sys.path[0] + "/.ssh_hosts"  #ssh登录信息保存在同目录的.ssh_hosts文件中

locale.setlocale(locale.LC_ALL, '')

child = None
tree = {'line_number': None, 'expanded': True, 'line': None, 'name': None, 'sub_lines': []}

def exit(signum, frame):
    sys.exit(1)

#用于pexpect设置屏幕大小，防止vim只显示半屏
def sigwinch_passthrough():
    s = struct.pack("HHHH", 0, 0, 0, 0)
    a = struct.unpack('hhhh', fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, s))
    if not child.closed:
        child.setwinsize(a[0], a[1])

def sigwinch_passthrough_with_param(sig, data):
    sigwinch_passthrough()

def _assert(exp, err):
    if not exp:
        print >>sys.stderr,err
        sys.exit(1)

def _dedup(ls):
    table = {}
    for item in ls:
        table[item] = None
    ls_dedup = table.keys()
    ls_dedup.sort()
    return ls_dedup

def _get_known_hosts():
    fn = os.path.expanduser('~/.ssh/known_hosts')
    hosts = []
    try:
        for line in open(fn, 'r'):
            tmp = line.split(' ')
            if not len(tmp) or not len(tmp[0]):
                continue
            host = tmp[0].split(',')[0]
            if host.find('[') != -1:
                m = re.match(r'\[([^\]]+)\]:(\d+)', host)
                if m is not None:
                    host = '%s -p %s' % m.groups()
            hosts.append(host)
    except IOError:
        return hosts
    return _dedup(hosts)

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
    KEY_EQUAL = 61 # =

    screen = None

    def _parse_tree_from_config_file(self, config_file):

        tree_level = None
        nodes_pool = []
        line_number = 0;


        for line in open(config_file, 'r'):
            line_number += 1
            line_con = line.strip()
            if line_con == '' or line_con[0] == '#':
                continue
            line_con_and_name = re.split(r'\s+#', line_con)
            line_con = line_con_and_name[0]
            name = line_con_and_name[1] if len(line_con_and_name) >= 2 else line_con_and_name[0]
            expand = True
            if line_con[0] == '-':
                line_con = line_con[1:]
                expand = False
            indent = re.findall(r'^[\t ]*(?=[^\t ])', line)[0]
            line_level = indent.count('    ') + indent.count('\t')
            if tree_level == None:
                _assert(line_level == 0, 'invalid indent,line:' + str(line_number))
            else:
                _assert(line_level <= tree_level
                        or line_level == tree_level + 1, 'invalid indent,line:' + str(line_number))
            tree_level = line_level

            new_node = {'level': tree_level, 'expanded': expand, 'line_number': line_number, 'line': line_con, 'name': name, 'sub_lines': []}
            nodes_pool.append(new_node)
            parent = self.find_parent_line(new_node)
            parent['sub_lines'].append(new_node)

        return tree, nodes_pool

    def find_parent_line(self, new_node):
        line_number = new_node['line_number']
        level = new_node['level']

        if level == 0:
            return tree

        stack = tree['sub_lines'] + []
        parent = None
        while len(stack):
            node = stack.pop()
            if node['line_number'] < line_number and node['level'] == level - 1:
                if parent is None:
                    parent = node
                elif node['line_number'] > parent['line_number']:
                    parent = node
            if len(node['sub_lines']) and node['level'] < level:
                stack = stack + node['sub_lines']
                continue

        return parent

    def __init__(self, config_file):

        self.hosts_tree, self.hosts_pool = self._parse_tree_from_config_file(config_file)

        known_host_list     = _get_known_hosts()

        if len(known_host_list):
            append_line_number  = self.hosts_pool[-1]['line_number'] + 1

            known_hosts = {'sub_lines':[],
                    'line_number':append_line_number,
                    'line':'known hosts',
                    'name': 'known hosts',
                    'expanded':False,
                    'level':0
                    }

            self.hosts_tree['sub_lines'].append(known_hosts)
            self.hosts_pool.append(known_hosts)

            for host in known_host_list:
                append_line_number += 1
                new_node = {
                    'sub_lines':[],
                    'line_number':append_line_number,
                    'line':host,
                    'name': host,
                    'expanded':True,
                    'level':1
                    }
                known_hosts['sub_lines'].append(new_node)
                self.hosts_pool.append(new_node)


        self.screen = curses.initscr()
        curses.noecho()
        curses.cbreak()
        curses.curs_set(0)
        self.screen.keypad(1)
        self.screen.border(0)

        self.top_line_number = 0
        self.highlight_line_number = 0
        self.search_keyword = None

        curses.start_color()
        curses.use_default_colors()

        #highlight
        curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_BLUE)
        self.COLOR_HIGHLIGHT = 2
        #red
        curses.init_pair(3, curses.COLOR_RED, -1)
        self.COLOR_RED = 3

        #red highlight
        curses.init_pair(4, curses.COLOR_RED, curses.COLOR_BLUE)
        self.COLOR_RED_HIGH = 4

        #white bg
        curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_WHITE)
        self.COLOR_WBG = 5

        #black bg
        curses.init_pair(6, curses.COLOR_BLACK, curses.COLOR_BLACK)
        self.COLOR_BBG = 6

        self.run()

    def run(self):
        while True:
            self.render_screen()
            c = self.screen.getch()
            if c == curses.KEY_UP or c == self.KEY_k:
                self.updown(-1)
            elif c == curses.KEY_DOWN or c == self.KEY_j:
                self.updown(1)
            elif c == self.KEY_u:   # 上翻页
                for i in range(0, curses.tigetnum('lines')):
                    self.updown(-1)
            elif c == self.KEY_d:   # 下翻页
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
        self.search_keyword = self.screen.getstr(0, 1)
        curses.noecho()
        curses.curs_set(0)

    def _get_visible_lines_for_render(self):
        lines = []
        stack = self.hosts_tree['sub_lines'] + []
        while len(stack):
            node = stack.pop()
            lines.append(node)
            if node['expanded'] and len(node['sub_lines']):
                stack = stack + node['sub_lines']

        lines.sort(key=lambda n:n['line_number'], reverse=False)
        return lines

    def _search_node(self):
        rt = []
        try:
            kre = re.compile(self.search_keyword, re.I)
        except:
            return rt
        for node in self.hosts_pool:
            if len(node['sub_lines']) == 0 and kre.search(node['name']) is not None:
                rt.append(node)
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
        linenum = self.top_line_number + self.highlight_line_number
        node = visible_hosts[linenum]
        if not len(node['sub_lines']):
            return
        stack = [node]
        while len(stack):
            node = stack.pop()
            node['expanded'] = True
            if len(node['sub_lines']):
                stack = stack + node['sub_lines']

    def close_node(self):
        visible_hosts = self.get_lines()
        linenum = self.top_line_number + self.highlight_line_number
        node = visible_hosts[linenum]
        if not len(node['sub_lines']):  # 如果当前不在node上，那么移动到node上后折叠node。
            parent_node = self.find_parent_line(node)
            increment = node['line_number'] - parent_node['line_number']
            for i in range(0, increment):
                self.updown(-1)
            self.close_node()
            return
        stack = [node]
        while len(stack):
            node = stack.pop()
            node['expanded'] = False
            if len(node['sub_lines']):
                stack = stack + node['sub_lines']

    def pre_node(self): # 关闭当前组，切换到上一组的最后一个
        self.close_node()
        self.updown(-1)
        visible_hosts = self.get_lines()
        linenum = self.top_line_number + self.highlight_line_number
        node = visible_hosts[linenum]
        if len(node['sub_lines']):
            self.open_node()
            for i in range(0, len(node['sub_lines'])):
                self.updown(1)

    def next_node(self): # 关闭当前组，切换到下一组的第一个
        self.close_node()
        self.updown(1)
        self.open_node()
        self.updown(1)
        
    def open_all(self):
        for node in self.hosts_pool:
            if len(node['sub_lines']):
                node['expanded'] = True

    def close_all(self):
        for node in self.hosts_pool:
            if len(node['sub_lines']):
                node['expanded'] = False

    def toggle_node(self):
        visible_hosts = self.get_lines()
        linenum = self.top_line_number + self.highlight_line_number
        node = visible_hosts[linenum]
        if len(node['sub_lines']):
            node['expanded'] = not node['expanded']
        else:
            self.restore_screen()
            self.doSSH(node)

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

        for (index,node,) in enumerate(nodes):
            #linenum = self.top_line_number + index

            line = node['name']
            if len(node['sub_lines']):
                line += '(%d)' % len(node['sub_lines'])

            prefix = ''
            if self.search_keyword is None:
                prefix += '  ' * node['level']
            if len(node['sub_lines']):
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
        #render scroll bar
        for i in xrange(screen_lines):
            self.screen.addstr(i, screen_cols - 2, ' ', curses.color_pair(self.COLOR_WBG))      # 滚动条填充

        scroll_top = int(math.ceil((self.top_line_number + 1.0) / max(len(all_nodes), screen_lines) * screen_lines - 1))
        scroll_height = int(math.ceil((len(nodes) + 0.0) / len(all_nodes) * screen_lines))
        highlight_pos = int(math.ceil(scroll_height * ((self.highlight_line_number + 1.0)/min(screen_lines, len(nodes)))))

        self.screen.addstr(scroll_top, screen_cols - 2, '^', curses.color_pair(self.COLOR_WBG))
        self.screen.addstr(min(screen_lines, scroll_top + scroll_height) - 1, screen_cols - 2, 'v', curses.color_pair(self.COLOR_WBG))
        self.screen.addstr(min(screen_lines, scroll_top + highlight_pos) - 1, screen_cols - 2, ' ', curses.color_pair(self.COLOR_RED))


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
        elif increment > 0 and next_line_number == curses.tigetnum('lines') and (self.top_line_number+curses.tigetnum('lines')) != visible_lines_count:
            self.top_line_number += self.DOWN
            return

        # scroll highlight line
        if increment < 0 and (self.top_line_number != 0 or self.highlight_line_number != 0):
            self.highlight_line_number = next_line_number
        elif increment > 0 and (self.top_line_number+self.highlight_line_number+1) != visible_lines_count and self.highlight_line_number != curses.tigetnum('lines'):
            self.highlight_line_number = next_line_number

    def restore_screen(self):
        curses.initscr()
        # nocbreak模式：字符先缓存，再输出
        curses.nocbreak()
        curses.echo()
        curses.endwin()

    # zssh 远程登录
    def doSSH(self, node):
        global child
        cmd = re.split(r'\s+#', node['line'])[0]  # 行内注释请另外在井号前加空格或tab
        cmd_expects = cmd.split(' --expect')
        ssh_param = cmd_expects[0]
        ssh = 'ssh'
        if os.popen('which zssh 2> /dev/null').read().strip() != '':
            ssh = 'zssh'
        child = pexpect.spawn(ssh + ' ' + ssh_param)
        sigwinch_passthrough()
        signal.signal(signal.SIGINT, exit)  # 捕获Ctrl+C信号
        signal.signal(signal.SIGTERM, exit) # 捕获Ctrl+C信号
        signal.signal(signal.SIGWINCH, sigwinch_passthrough_with_param) # 捕获窗口大小调整信号
        child.logfile_read = sys.stdout # 只将从远端读到的内容打印到屏幕
        if len(cmd_expects) == 2:
            expects = json.loads(cmd_expects[1], object_pairs_hook=OrderedDict)
            for expect in expects:
                for key in expect:
                    if key == 'passwd':
                        i = child.expect([pexpect.TIMEOUT, r'Are you sure you want to continue connecting \(yes/no\)\?', '[Pp]assword: ','密码：', '[$#] '])
                        if i == 0:  # Timeout
                            print('\033[1;31;40mTimeout !\033[0m')
                            sys.exit(1)
                        if i == 1:  # SSH does not have the public key. Just accept it.
                            child.sendline('yes')
                            child.expect(['[Pp]assword: ','密码：'])   
                        if i == 4:  # 用于提供了密码但是实际不需要输入密码就进去了的情况
                            child.sendline('')  # 走到这里表示已经匹配了一次[$#]。配置文件中可能有下一步也是匹配[$#]的,故需要让流再次输出一次关键字$或#供下次匹配。
                            continue
                        child.sendline(expect[key])
                    elif key == 'ps1' or key == 'ps1-prod':
                        i = child.expect([pexpect.TIMEOUT,'[$#] '])
                        if i == 0:  # Timeout
                            print('\033[1;31;40mTimeout!\033[0m')
                            sys.exit(1)
                        if i == 1:
                            if key == 'ps1':
                                child.sendline("export PS1='\\[\\e[36;47m\\]" + expect[key] + ":\\w\\[\\e[37;46m\\]▶\\[\\e[30;46m\\]\\t \\$\\[\\e[36;40m\\]▶\\[\\e[0m\\]\\[\\e[36m\\]'")
                                # child.sendline("export PS1='\\[\\e[36;47m\\]" + expect[key] + ":\\w\\[\\e[37;46m\\]▶\\[\\e[30;46m\\]\\t \\$\\[\\e[36;40m\\]▶\\[\\e[0m\\]\\[\\e[36m\\]'\r")
                            else:
                                child.sendline("export PS1='\\[\\e[36;47m\\]" + expect[key] + ":\\w\\[\\e[37;43m\\]▶\\[\\e[30;43m\\]\\t \\$\\[\\e[33;40m\\]▶\\[\\e[0m\\]\\[\\e[33m\\]'")
                                # child.sendline("export PS1='\\[\\e[36;47m\\]" + expect[key] + ":\\w\\[\\e[37;43m\\]▶\\[\\e[30;43m\\]\\t \\$\\[\\e[33;40m\\]▶\\[\\e[0m\\]\\[\\e[33m\\]'\r")
                    else:
                        #i = child.expect([pexpect.TIMEOUT, key],timeout=10)
                        i = child.expect_exact([pexpect.TIMEOUT, key],timeout=60)
                        if i == 0:  # Timeout
                            print('\033[1;31;40mTimeout! Cannot capture string "%s".\033[0m' % key)
                            sys.exit(1)
                        if i == 1:
                            child.sendline(expect[key])
        child.sendline("PROMPT_COMMAND='echo -ne \"\\033]0;" + node['name'] + "\\007\"'")   #设置本地终端的标题
        child.logfile_read = None
        child.interact()
        curses.cbreak() # cbreak模式：除delete,ctrl等控制键外，其他的输入字符被立即读取
        if self.search_keyword is not None:
            self.search_keyword = None #退出远程连接返回到本程序后退出搜索模式

    # catch any weird termination situations
    def __del__(self):
        self.restore_screen()


if __name__ == '__main__':
    parser = OptionParser()
    parser.add_option('-c', '--config', help='use specified config file instead of ~/.ssh_hosts')
    options, args = parser.parse_args(sys.argv)
    host_file = os.path.expanduser(sshHosts)

    if options.config is not None:
        host_file = options.config
    if not os.path.exists(host_file):
        print >>sys.stderr, sshHosts, ' is not found, create it'
        fp = open(host_file, 'w')
        fp.close()

    sshgo = SSHGO(host_file)
