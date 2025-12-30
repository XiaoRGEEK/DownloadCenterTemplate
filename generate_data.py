#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从零开始生成data.json
只根据文件名后缀区分平台，不依赖文件夹结构
"""

import os
import re
import json
from typing import List, Dict, Any, Tuple

# 外部链接, 如果有其他的产品，没有在本地的，可以通过外部链接的方式添加进来，一个典型的示例如下
External_Links = {
    "XRBlock": {
        "en": "XRBlock Scratch3.0 Software",
        "zh": "XRBlock 图形化编程PC端软件",
        "desc_en": "Support Scratch3.0 porducts",
        "desc_zh": "支持图形化编程系列产品",
        "logo": "./software/image/xrblock.png",
        # 各个平台对应的版本以及url和平台
        "version": ["v2.2.5"],
        "url": ["//software.xiao-r.com/software/pc/XR Block v2.2.5.exe"],
        "platform": ["Windows"]
    },
}

# 软件信息字典
SOFTWARE_INFO = {
    "RoboManager": {
        "en": "RoboManager",
        "zh": "RoboManager机器人控制软件",
        "desc_en": "Support SamuRoid and VortaBot humanoid bipedal robots",
        "desc_zh": "支持SamuRoid机甲武士和VortaBot人形双足机器人",
        "logo": "./software/image/RoboManager.png"
    },
    "XR-Controller": {
        "en": "XR-Controller", 
        "zh": "XR-Controller机器人控制器",
        "desc_en": "Support X-series, Jetbot V2.0, DonkeyCar and Bionic robots",
        "desc_zh": "支持 X 系列、Jetbot V2.0、DonkeyCar 和仿生机器人",
        "logo": "./software/image/xr-controller.png"
    },
    "ROSXRMobile": {
        "en": "ROSXRMobile",
        "zh": "ROSXRMobile移动端控制软件",
        "desc_en": "Support jetson nano, raspberry pi and sunrise ros series robot",
        "desc_zh": "支持 jetson nano、树莓派和地平线等ros系列机器人",
        "logo": "./software/image/rosxrmobile.png"
    },
    "ROS2Mobile": {
        "en": "ROS2Mobile",
        "zh": "ROS2Mobile移动端控制软件", 
        "desc_en": "A ROS2 Android App",
        "desc_zh": "ROS2机器人控制APP",
        "logo": "./software/image/ros2mobile.png"
    },
    "ROSCollie": {
        "en": "ROSCollie",
        "zh": "ROSCollie四足机器人控制",
        "desc_en": "Collie dog ROS application",
        "desc_zh": "ROS大四足狗应用",
        "logo": "./software/image/roscollie.png",
        "tools": [
            {
                "name": "XRCollieTool",
                "desc_zh": "舵机偏差调节工具",
                "desc_en": "Servo deviation adjustment tool",
                "logo": "./software/image/XRCollieTool.png"
            }
        ]
    },
    "WifiRobot": {
        "en": "WifiRobot(No longer maintained, use XR-Controller)",
        "zh": "WifiRobot无线机器人控制",
        "desc_en": "Wireless Robot Car control software",
        "desc_zh": "无线机器人小车控制软件",
        "logo": "./software/image/wifirobot.png"
    },
    "DonkeyCar": {
        "en": "XR-DonkeyCar (No longer maintained)",
        "zh": "XR-DonkeyCar驴车控制(不再维护)",
        "desc_en": "DonkeyCar control application",
        "desc_zh": "驴车APP控制软件",
        "logo": "./software/image/donkeycar.png"
    },
    "WuliBot": {
        "en": "WuliBot",
        "zh": "WuliBot瓦力机器人控制",
        "desc_en": "Support wulibot robot",
        "desc_zh": "支持瓦力机器人",
        "logo": "./software/image/wulibot.png"
    },
    "XRBitCar": {
        "en": "XRBitCar",
        "zh": "XRBitCar Micro:bit编程",
        "desc_en": "Micro:bit Robot Control and programming APP",
        "desc_zh": "Micro:bit图形化编程APP",
        "logo": "./software/image/xrbitcar.png"
    },
    "Hexapod": {
        "en": "Hexapod",
        "zh": "Hexapod六足机器人",
        "desc_en": "Hexapod robot control software",
        "desc_zh": "六足机器人控制软件",
        "logo": "./software/image/hexapod.png"
    },
    "smart-arm": {
        "en": "AI Robotic-Arm",
        "zh": "AI机械臂控制软件",
        "desc_en": "AI Robotic-Arm control software",
        "desc_zh": "AI六自由度树莓派机械臂控制软件",
        "logo": "./software/image/smart-arm.png"
    },
    "RobotKit": {
        "en": "RobotKit",
        "zh": "RobotKit编程软件",
        "desc_en": "PWM Servo programming software",
        "desc_zh": "24路PWM舵机编程软件",
        "logo": "https://www.cleverfiles.com/howto/wp-content/uploads/2018/04/what-is-zip.png"
    },
    "xr-servo": {
        "en": "XR Servo Control Terminal",
        "zh": "小R总线舵机控制终端",
        "desc_en": "Bus Servo control terminal software",
        "desc_zh": "小R总线舵机控制终端软件",
        "logo": "./software/image/xr-servo.png"
    },
    "Corgi": {
        "en": "Corgi for iOS",
        "zh": "Corgi iOS版",
        "desc_en": "Support Bionic robots like hexapod, corgi dog",
        "desc_zh": "支持六足机器人、柯基狗等仿生机器人的苹果APP",
        "logo": "./software/image/xr-controller_IOS.png"
    }
}


def parse_version(version_str: str) -> Tuple:
    """解析版本号为可比较的元组"""
    if version_str == "unknown":
        return (0,)
    
    clean_version = version_str.lower().lstrip('v')
    parts = []
    for part in re.split(r'[\.\-_]', clean_version):
        try:
            parts.append(int(part))
        except ValueError:
            if part:
                parts.append(part)
    return tuple(parts)


def extract_software_info(filename: str) -> Dict[str, Any]:
    """从文件名提取软件信息和版本号"""
    name_without_ext = os.path.splitext(filename)[0]
    file_ext = os.path.splitext(filename)[1].lower()
    
    # 确定平台 - 只根据文件后缀
    platform = None
    if file_ext == '.apk':
        platform = "android"
    elif file_ext in ['.exe', '.zip']:
        platform = "windows"
    elif file_ext in ['.dmg']:
        platform = "mac"
    elif file_ext in ['.png', '.jpg', '.jpeg']:
        platform = "ios"
    
    # 如果无法确定平台，跳过该文件
    if platform is None:
        return None
    
    # 提取版本号
    version_patterns = [
        r'(\d+\.\d+\.\d+)',  # 1.0.48
        r'[vV](\d+\.\d+)',   # v1.4
        r'(\d+\.\d+)',       # 2.37
    ]
    
    version = None
    software_name = None
    
    for pattern in version_patterns:
        match = re.search(pattern, name_without_ext)
        if match:
            version = match.group(1)
            break
    
    if not version:
        version = "unknown"
    
    # 提取软件名称
    for known_name in SOFTWARE_INFO.keys():
        if known_name.lower() in name_without_ext.lower():
            software_name = known_name
            break
    
    if not software_name:
        # 如果没有匹配到已知名称，使用文件名作为软件名
        software_name = re.sub(r'[vV]?\d+\.\d+(\.\d+)*.*', '', name_without_ext).strip('-_')
        if not software_name:
            software_name = name_without_ext
    
    return {
        'software_name': software_name,
        'version': version,
        'platform': platform,
        'file_ext': file_ext,
        'filename': filename
    }


def scan_software_files(software_dir: str = "software") -> Dict[str, Dict]:
    """扫描software目录，返回按软件和平台分组的文件信息"""
    software_data = {}
    
    print("扫描software目录...")
    
    # 递归扫描所有子目录，但跳过image文件夹
    for root, dirs, files in os.walk(software_dir):
        # 跳过image目录
        if 'image' in root.split(os.sep):
            continue
            
        for filename in files:
            file_path = os.path.join(root, filename).replace("\\", "/")
            
            # 处理所有文件，只根据后缀判断平台
            file_info = extract_software_info(filename)
            if file_info is None:
                continue
                
            file_info['file_path'] = file_path
            
            software_name = file_info['software_name']
            if software_name not in software_data:
                software_data[software_name] = {'android': [], 'windows': [], 'mac': [], 'ios': []}
            
            platform = file_info['platform']
            
            # 确保平台是有效的
            if platform in ['android', 'windows', 'mac', 'ios']:
                software_data[software_name][platform].append(file_info)
                print(f"找到软件: {software_name} 版本: {file_info['version']} 平台: {platform} 文件: {filename}")
            else:
                print(f"跳过文件: {filename} - 未知平台: {platform}")
    
    print(f"扫描完成，共找到 {len(software_data)} 个软件")
    return software_data


def get_latest_versions(software_data: Dict) -> Dict[str, Dict]:
    """获取每个软件每个平台的最新版本"""
    latest_versions = {}
    
    for software_name, platforms in software_data.items():
        latest_versions[software_name] = {}
        
        for platform, files in platforms.items():
            if files:
                # 按版本号排序，获取最新版本
                sorted_files = sorted(files, key=lambda x: parse_version(x['version']), reverse=True)
                latest_version = sorted_files[0]
                old_versions = sorted_files[1:]
                
                latest_versions[software_name][platform] = {
                    'latest': latest_version,
                    'old_versions': old_versions
                }
    
    return latest_versions


def scan_tools_files(software_data: Dict) -> Dict[str, Dict]:
    """扫描并处理工具软件文件"""
    tools_data = {}
    
    print("扫描工具软件文件...")
    
    # 检查SOFTWARE_INFO中哪些软件有tools字段
    for software_name, software_info in SOFTWARE_INFO.items():
        if 'tools' in software_info and software_info['tools']:
            print(f"软件 {software_name} 包含工具: {[tool['name'] for tool in software_info['tools']]}")
            
            for tool_info in software_info['tools']:
                tool_name = tool_info['name']
                
                # 在软件数据中查找对应的工具软件
                if tool_name in software_data:
                    tool_platforms = software_data[tool_name]
                    
                    # 获取工具的最新版本信息
                    latest_tool_version = None
                    for platform, files in tool_platforms.items():
                        if files:
                            # 按版本号排序，获取最新版本
                            sorted_files = sorted(files, key=lambda x: parse_version(x['version']), reverse=True)
                            latest_tool_version = sorted_files[0]
                            break
                    
                    if latest_tool_version:
                        if software_name not in tools_data:
                            tools_data[software_name] = []
                        
                        tools_data[software_name].append({
                            'name': tool_name,
                            'desc_zh': tool_info.get('desc_zh', ''),
                            'desc_en': tool_info.get('desc_en', ''),
                            'logo': tool_info.get('logo', ''),
                            'version': latest_tool_version['version'],
                            'file_path': latest_tool_version['file_path'],
                            'platform': latest_tool_version['platform']
                        })
                        print(f"找到工具: {tool_name} 版本: {latest_tool_version['version']} 平台: {latest_tool_version['platform']}")
                    else:
                        print(f"警告: 未找到工具 {tool_name} 的软件文件")
                else:
                    print(f"警告: 工具 {tool_name} 在软件数据中不存在")
    
    print(f"扫描完成，共找到 {sum(len(tools) for tools in tools_data.values())} 个工具")
    return tools_data


def generate_data_json(latest_versions: Dict, tools_data: Dict) -> List[Dict]:
    """生成data.json数据结构"""
    data = []
    
    for software_name, platforms in latest_versions.items():
        if software_name not in SOFTWARE_INFO:
            continue
            
        software_info = SOFTWARE_INFO[software_name]
        
        # 收集该软件所有平台的版本信息
        platform_versions = {}
        for platform, versions in platforms.items():
            if versions:
                latest = versions['latest']
                platform_versions[platform] = f"v{latest['version']}" if latest['version'] != "unknown" else "v1.0"
        
        # 检查该软件是否有工具
        has_tools = software_name in tools_data and len(tools_data[software_name]) > 0
        
        # 为每个平台创建单独的条目
        for platform, versions in platforms.items():
            if not versions:
                continue
                
            latest = versions['latest']
            old_versions = versions['old_versions']
            
            # 确定按钮名称和链接 - 只根据文件后缀
            btn_names_en = []
            btn_names_zh = []
            links = []
            
            if platform == "android":
                btn_names_en = ["Android"]
                btn_names_zh = ["Android"]
                links = [latest['file_path']]
            elif platform == "windows":
                btn_names_en = ["Windows"]
                btn_names_zh = ["Windows"]
                links = [latest['file_path']]
            elif platform == "mac":
                btn_names_en = ["Mac"]
                btn_names_zh = ["Mac"]
                links = [latest['file_path']]
            elif platform == "ios":
                btn_names_en = ["iOS Code"]
                btn_names_zh = ["iOS 二维码"]
                links = [latest['file_path']]
            
            # 构建旧版本链接列表
            old_version_links = [v['file_path'] for v in old_versions]
            
            # 创建数据条目
            entry = {
                "logoSrc": software_info['logo'],
                "name": {
                    "en": software_info['en'],
                    "zh": software_info['zh']
                },
                "version": f"v{latest['version']}" if latest['version'] != "unknown" else "v1.0",
                "desc": {
                    "en": software_info['desc_en'],
                    "zh": software_info['desc_zh']
                },
                "link": links,
                "btnNames": {
                    "en": btn_names_en,
                    "zh": btn_names_zh
                },
                "oldVersion": old_version_links,
                "platform": platform,
                "platformVersions": platform_versions,  # 添加各平台版本信息
                "hasTools": has_tools,  # 标记该软件是否有工具
                "tools": tools_data.get(software_name, [])  # 添加工具信息
            }
            
            data.append(entry)
            print(f"生成条目: {software_info['en']} - {platform} - 版本: {latest['version']} - 旧版本: {len(old_versions)} - 工具: {len(tools_data.get(software_name, []))}")
    
    return data


def generate_external_links_data() -> List[Dict]:
    """生成External_Links的数据条目"""
    data = []
    
    for software_name, info in External_Links.items():
        # 获取基本信息
        en_name = info.get('en', software_name)
        zh_name = info.get('zh', software_name)
        desc_en = info.get('desc_en', '')
        desc_zh = info.get('desc_zh', '')
        logo = info.get('logo', '')
        versions = info.get('version', ['v1.0'])
        urls = info.get('url', [])
        platforms = info.get('platform', [])
        
        # 确保versions, urls, platforms是列表
        if not isinstance(versions, list):
            versions = [versions]
        if not isinstance(urls, list):
            urls = [urls]
        if not isinstance(platforms, list):
            platforms = [platforms]
        
        # 确定最大长度
        length = min(len(versions), len(urls), len(platforms))
        if length == 0:
            print(f"警告: External_Links 条目 {software_name} 缺少version、url或platform，跳过")
            continue
        
        for i in range(length):
            version = versions[i]
            url = urls[i]
            platform_raw = platforms[i]
            
            # 标准化平台字符串为小写
            platform_lower = platform_raw.lower()
            platform = None
            if platform_lower in ['android', 'windows', 'mac', 'ios']:
                platform = platform_lower
            else:
                # 尝试映射常见平台名称
                if 'android' in platform_lower:
                    platform = 'android'
                elif 'windows' in platform_lower:
                    platform = 'windows'
                elif 'mac' in platform_lower or 'osx' in platform_lower:
                    platform = 'mac'
                elif 'ios' in platform_lower or 'iphone' in platform_lower:
                    platform = 'ios'
                else:
                    print(f"警告: External_Links 条目 {software_name} 平台 '{platform_raw}' 无法识别，跳过")
                    continue
            
            # 确定按钮名称
            btn_names_en = []
            btn_names_zh = []
            if platform == "android":
                btn_names_en = ["Android"]
                btn_names_zh = ["Android"]
            elif platform == "windows":
                btn_names_en = ["Windows"]
                btn_names_zh = ["Windows"]
            elif platform == "mac":
                btn_names_en = ["Mac"]
                btn_names_zh = ["Mac"]
            elif platform == "ios":
                btn_names_en = ["iOS Code"]
                btn_names_zh = ["iOS 二维码"]
            
            # 平台版本信息（仅当前平台）
            platform_versions = {platform: version}
            
            entry = {
                "logoSrc": logo,
                "name": {
                    "en": en_name,
                    "zh": zh_name
                },
                "version": version,
                "desc": {
                    "en": desc_en,
                    "zh": desc_zh
                },
                "link": [url],
                "btnNames": {
                    "en": btn_names_en,
                    "zh": btn_names_zh
                },
                "oldVersion": [],
                "platform": platform,
                "platformVersions": platform_versions,
                "hasTools": False,
                "tools": []
            }
            data.append(entry)
            print(f"生成外部链接条目: {en_name} - {platform} - 版本: {version}")
    
    return data


def main():
    """主函数"""
    print("=== 从零开始生成data.json (仅根据文件后缀区分平台) ===")
    
    # 扫描软件文件
    software_data = scan_software_files()
    
    # 获取最新版本
    latest_versions = get_latest_versions(software_data)
    
    # 扫描工具文件
    tools_data = scan_tools_files(software_data)
    
    # 生成data.json数据
    data = generate_data_json(latest_versions, tools_data)
    
    # 添加外部链接数据
    external_data = generate_external_links_data()
    data.extend(external_data)
    
    # 保存到文件
    with open("data.json", 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    
    print(f"\n=== 完成 ===")
    print(f"已生成包含 {len(data)} 个条目的data.json文件")
    print(f"包含工具信息的软件: {[name for name, tools in tools_data.items() if tools]}")
    print(f"外部链接条目: {len(external_data)} 个")
    print("现在可以修改index.html实现新的界面设计")


if __name__ == "__main__":
    main()