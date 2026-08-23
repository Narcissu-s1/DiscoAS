import json
import os
import re

import requests


class SpotifyEmbedScraper:
    def __init__(self):
        self.session = requests.Session()
        # 伪装为普通浏览器
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
        })

    def _get_embed_data(self, url):
        """访问 Spotify Embed 页面并提取内部的 JSON 数据"""
        try:
            res = self.session.get(url, timeout=10)
            res.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"网络请求失败，请检查网络环境或代理设置！具体报错: {e}")

        # 利用正则提取 Next.js 注入的页面状态 JSON
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', res.text)
        if not match:
            raise RuntimeError(f"无法在页面源码中找到 __NEXT_DATA__ 节点，Spotify 可能更改了网页结构。\n请求的URL: {url}")

        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            raise RuntimeError("解析内部 JSON 失败。")

    def _extract_entity(self, data):
        """从解析的 JSON 中提取出核心数据实体 (Entity)"""
        try:
            # 数据通常储存在这个路径下
            return data["props"]["pageProps"]["state"]["data"]["entity"]
        except KeyError:
            raise RuntimeError("JSON 结构有变，无法找到 entity 数据。")

    def get_track_details(self, track_id):
        """获取完整的歌曲详情 JSON"""
        url = f"https://open.spotify.com/embed/track/{track_id}"
        data = self._get_embed_data(url)
        return self._extract_entity(data)

    def get_playlist_details(self, playlist_id):
        """获取完整的歌单详情 JSON"""
        url = f"https://open.spotify.com/embed/playlist/{playlist_id}"
        data = self._get_embed_data(url)
        return self._extract_entity(data)

    def get_album_details(self, album_id):
        """获取完整的专辑详情 JSON"""
        url = f"https://open.spotify.com/embed/album/{album_id}"
        data = self._get_embed_data(url)
        return self._extract_entity(data)


def save_json_to_file(data, filename):
    """辅助函数：将字典保存为格式化好的 JSON 文件"""
    with open(filename, 'w', encoding='utf-8') as f:
        # indent=4 保证输出的 JSON 是格式化缩进的，方便人类阅读
        # ensure_ascii=False 保证中文/日文等多字节字符正常显示，不被转码为 \uXXXX
        json.dump(data, f, indent=4, ensure_ascii=False)
    print(f"✅ 成功保存文件: {os.path.abspath(filename)}")


# ==================== 测试保存样例 ====================
if __name__ == "__main__":
    scraper = SpotifyEmbedScraper()

    # 你提供的测试 ID
    TRACK_ID = "3T0UCGe1Vrfh57fM1B0Mgi"
    ALBUM_ID = "0BFsMVKknLEGhXFNeB4tpI"
    PLAYLIST_ID = "1sgp26qrilxbD03gFB2UUt"

    print("开始抓取数据，请稍候...\n")

    # 1. 获取并保存歌曲 JSON
    try:
        print(f"正在抓取歌曲[{TRACK_ID}] ...")
        track_data = scraper.get_track_details(TRACK_ID)
        save_json_to_file(track_data, f"track_{TRACK_ID}.json")
    except Exception as e:
        print(f"❌ 抓取歌曲失败: {e}")

    # 2. 获取并保存专辑 JSON
    try:
        print(f"\n正在抓取专辑[{ALBUM_ID}] ...")
        album_data = scraper.get_album_details(ALBUM_ID)
        save_json_to_file(album_data, f"album_{ALBUM_ID}.json")
    except Exception as e:
        print(f"❌ 抓取专辑失败: {e}")

    # 3. 获取并保存歌单 JSON
    try:
        print(f"\n正在抓取歌单 [{PLAYLIST_ID}] ...")
        playlist_data = scraper.get_playlist_details(PLAYLIST_ID)
        save_json_to_file(playlist_data, f"playlist_{PLAYLIST_ID}.json")
    except Exception as e:
        print(f"❌ 抓取歌单失败: {e}")

    print("\n🎉 全部任务执行完毕！请在当前目录下查看生成的 JSON 文件。")
