sshgo
=====

​	用于管理ssh主机列表的脚本

- 支持自动输入密码
- 支持登录后自动执行命令
- 支持登录后自动跳转到其他机器。（即所谓跳板机登录）
- 支持终端自动设置Title（仅支持bash）

## 预览图
![screenshot](https://raw.github.com/mokyle/sshgo/master/screenshot.png)

## 依赖

[pexpect](https://pexpect.readthedocs.io/en/latest/install.html) 

## .ssh_hosts 示例

    +lo
        root@127.0.0.1 --expect [{"password:":"123456789"}] #localhost
        docker@127.0.0.1 -p 7700 --expect [{"password:":" "}, {"$":"sudo su"}] #docker
    +me
        root@192.168.31.1 --expect [{"passwd":"123456789"}] #missh
        root@192.168.31.4 --expect [{"passwd":"123456789"}, {"ps1":"server"}] #31.4
        root@192.168.31.1 --expect [{"passwd":"123456789"}, {"#":"ssh root@192.168.31.4 && exit"}, {"Do you want to continue connecting?":"y"}, {"passwd":"123456789"}, {"ps1-prod":"\\h"}] #missh->server

## 使用说明

![usage](https://raw.github.com/mokyle/sshgo/master/usage.png)

## 快捷键

* 退出: q
* 上一屏: k
* 下一屏: j
* 上翻页: u
* 下翻页: d
* 进入主机: space 或 Enter 或 Right
* 搜索: /
* 退出搜索: q
* 展开组: o 或 Right
* 折叠组: c 或 Left
* 展开所有组: O
* 折叠所有组: C
* 上一组：PgUp 或 -
* 下一组：PgDn 或 =
