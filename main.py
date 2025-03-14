from argparse import ArgumentParser
from datetime import datetime, timedelta, timezone
import json
import random
import os

from atproto import Client, client_utils, models
from atproto.exceptions import BadRequestError
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry


with open('12h_news.json') as f:
    latest_12h_news = []
    latest_12h_news_url = []
    before_12h = datetime.now() - timedelta(hours=12)
    for item in json.loads(f.read()):
        if datetime.strptime(item['send_time'], "%m/%d/%Y %H:%M:%S") > before_12h:
            latest_12h_news.append(item)
            latest_12h_news_url.append(item['url'])


def fetch_news(lm_id, date):
    s = requests.Session()
    response = s.get(f'https://api.cntv.cn/NewVideo/getVideoListByColumn?id={lm_id}&bd={date}&serviceId=tvcctv&n=100', allow_redirects=False)
    assert response.status_code == 200, response.status_code
    news_data = response.json()

    if 'errcode' in news_data:
        print(f'fetch news error: {json.dumps(news_data)}')
        return

    news_box = []

    for news in news_data['data']['list']:
        if news['mode'] == 0:
            continue

        news_box.append({
            'title': news["brief"],
            'time': news['time'],
            'url': news['url'],
            'imgurl': news['image']
        })
    return news_box


def raw_fetch_img(url, proxy=None):
    response = requests.get(url, allow_redirects=False, proxies={'http': proxy, 'https': proxy} if proxy else None)
    assert response.status_code == 200, f'status code: {response.status_code}'
    assert response.headers['Content-Type'].startswith('image/'), f'content type is not image'
    return response


def fetch_img(url):
    try:
        response = raw_fetch_img(url)
    except Exception as error:
        print(f'fetch img: {url} error:{error}')
        return
    return response.content


lm_ids = {
    'xwlb': 'TOPC1451528971114112',
    'xw30f': 'TOPC1451559097947700',
}


def send_post(client, post, embed, langs):
    try:
        client.send_post(post, embed=embed, langs=langs)
    except BadRequestError as error:
        if 'BlobTooLarge' in str(error) and embed.external.thumb is not None:
            embed.external.thumb = None
            send_post(client, post, embed, langs)
        else:
            raise error


def git_commit():
    os.system('git config --global user.email "xiaopengyou@live.com"')
    os.system('git config --global user.name "robot auto"')
    os.system('git add .')
    os.system('git commit -m "update from robot"')


def git_push():
    os.system('git push')


def main(lm, service, username, password, dev, date):
    assert lm in lm_ids
    beijing_tz = timezone(timedelta(hours=8))
    news_box = fetch_news(lm_ids[lm], date or datetime.now(beijing_tz).strftime('%Y%m%d'))
    assert news_box is not None
    print(f'fetch news: {len(news_box)}')

    post_box = []
    for news in news_box:
        if news['url'] in latest_12h_news_url:
            continue

        if len(news['title']) > 200:
            news['title'] = news['title'][:200] + '...'
        news['post'] = client_utils.TextBuilder().link(news['title'], news['url']).text(f'\n{news["time"]} ')
        news['img'] = fetch_img(news['imgurl'])
        post_box.append(news)

    print(f'need posts: {len(post_box)}')
    if not post_box:
        return

    if dev:
        post_box = post_box[:3]

    client = Client(base_url=service if service != 'default' else None)
    client.login(username, password)
    post_status_error = False
    updated = False

    for post in post_box:
        thumb = None
        if post['img'] is not None:
            thumb = client.upload_blob(post['img'])

        embed = models.AppBskyEmbedExternal.Main(
            external=models.AppBskyEmbedExternal.External(
                title=post['title'],
                description=post['title'],
                uri=post['url'],
                thumb=thumb.blob if thumb else None,
            )
        )
        try:
            send_post(client, post['post'], embed=embed, langs=['zh'])
            latest_12h_news.append({
                'url': post['url'],
                'send_time': datetime.now().strftime('%m/%d/%Y %H:%M:%S')
            })
            updated = True
        except Exception as error:
            post_status_error = True
            print(f'error: {error} when handle post: {post["title"]} {post["url"]} {post["imgurl"]}')

    if updated:
        with open('12h_news.json', 'w') as f:
            f.write(json.dumps(latest_12h_news))

        if not dev:
            git_commit()
            git_push()

    assert post_status_error is False


if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument("--lm", help="栏目")
    parser.add_argument("--service", help="service")
    parser.add_argument("--username", help="username")
    parser.add_argument("--password", help="password")
    parser.add_argument("--dev", action="store_true")
    parser.add_argument("--date", help='date')
    args = parser.parse_args()
    main(args.lm, args.service, args.username, args.password, args.dev, args.date)
