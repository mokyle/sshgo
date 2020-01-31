sshgo
=====

​	用于管理ssh主机列表的脚本，并且支持自动输入，可用于：

- 自动输入密码
- 登录后自动执行命令
- 登录后自动ssh跳转到其他机器。（即所谓跳板机登录）
- 支持终端自动设置Title（仅支持部分终端的bash）

## 预览图
![screenshot](https://raw.github.com/mokyle/sshgo/master/screenshot.png)

## 依赖

ssh或zssh python3 [pexpect](https://pexpect.readthedocs.io/en/latest/install.html) 

## 配置文件ssh_hosts.json 示例

    [
        {
            "title": "me",
            "expanded": false,
            "sub_node": [
                {
                    "title": "local",
                    "ssh": "k@127.0.0.1 -p 22",
                    "expect": [
                        {"passwd": "123456"}
                    ]
                },
                {
                    "title": "localToTemp",
                    "pre_host": "local",
                    "expect": [
                        {"$": "cd /tmp/"},
                        {"ps1": "inTempPath"},
                        {"setTitle": ""}
                    ]
                }
            ]
        },
        {
            "title": "prod",
            "expanded": true,
            "sub_node": [
                {
                    "title": "manualLocal",
                    "ssh": "k@127.0.0.1 -p 22",
                    "expect": [
                        {"k@127.0.0.1's password:": " "},
                        {"$": "cd /tmp/"}
                    ]
                },
                {
                    "title": "ping",
                    "pre_host": "localToTemp",
                    "expect": [
                        {"$": "ping -c 3 127.0.0.1 && sleep 5 && exit"}
                    ]
                }
            ]
        }
    ]

## 配置文件详解：

*首先效果见上图。*

配置文件中有两个组，共包含4个主机的配置。

参数含义：

- title				表示在主界面显示的名称。
- expanded 	表示组是否默认展开。 （示例配置中"me"组是默认没展开的。图中展示的"me"组是按右方向键或回车键手动展开后的效果。）

- sub_node     表示组里包含的具体的host
- ssh               表示要登录指定主机时候需要的ssh命令具体参数
- expect          表示ssh登录指定主机时候或登录到指定主机之后要自动执行的命令。例如 示例配置文件中主机manualLocal 示例中："expect":[{"k@127.0.0.1's password:":"123456"},{"$":"cd /tmp/"}]，意思是：ssh尝试登录主机，收到请输入密码的提示: "k@127.0.0.1's password:"，此脚本自动输入密码123456并回车，然后此脚本会等待出现"$",刚回车后ssh命令继续执行进入bash登录成功并显示了一个$符号表示是普通用户登录成功。此脚本捕获到出现的"$"后又自动执行"cd /tmp/"并回车。 （这里有个麻烦的地方是每个主机的密码提示语可能都不太一样，运行示例时候请将"k@127.0.0.1's password:"改为自己目标主机实际的提示语。另外为了解决这个麻烦，脚本支持关键字"passwd"，可以自动识别各种密码提示语，详见下文）

>  注意： expect 参数的类型是数组，数组里面放{}，可以有多个{}，但每个{}中应该有且仅有一个键值对。为什么这么设计而不是设计成 expect:{"key1":"value1","key2":"value2"}呢? 原因是数组可以保证顺序。
>
> 对于expect数组中每个{}的键值对：
>
> 键表示等待出现的字符串， 值表示自动发送的内容。 另外，键有预设的几个关键字，目前有"passwd", "setTitle","ps1"。
>
> - passwd	表示请输入密码的提示，可以同时匹配中文和英文密码提示，也支持第一次连接某个新主机时自动确认是否信任新秘钥。
> - setTitle     设置终端显示的标题。其实就是登录成功后执行一条命令：PROMPT_COMMAND='echo -ne "\033]0;sshToLocal\007"' 。已知深度终端是默认支持的，如果是konsole，需要设置konsole的 配置方案->标签页->标签标题格式为%w
>
> - ps1           表示登陆后自动设置bash的PS1变量（即终端的提示符）。值留空时，表示使用title的值。脚本里面预设了PS1的格式，效果见下图：(如果运行后▶符号显示的不如下图完美，可以使用我提供的这款字体[Hack-Regular-kai.ttf](https://github.com/mokyle/sshgo/blob/master/Hack-Regular-kai.ttf))

![screenshot](https://raw.github.com/mokyle/sshgo/master/PS1.png)

- pre_host       值为其他主机中的title值。表示此主机配置是基于某个主机配置，有了pre_host参数就不再需要ssh参数。 比如示例文件中localToTemp主机，执行登录时先执行local主机的ssh命令，然后执行local主机的expect，然后再执行localToTemp主机的expect。

## 快捷键

* 上一组：PgUp 或 -
* 下一组：PgDn 或 =
* 进入主机: space 或 Enter 或 Right
* 搜索: /
* 退出或退出搜索: q
* 上一屏: k
* 下一屏: j
* 上翻页: u
* 下翻页: d
* 展开组: o 或 Right
* 折叠组: c 或 Left
* 展开所有组: O
* 折叠所有组: C
