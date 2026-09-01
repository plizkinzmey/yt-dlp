import base64
import json
import unittest

from yt_dlp import YoutubeDL
from yt_dlp.extractor.threads import ThreadsIE
from yt_dlp.utils import ExtractorError


def _efg(duration_s, width=720):
    blob = json.dumps({
        'vencode_tag': f'xpv_progressive.INSTAGRAM.FEED.C3.{width}.dash_baseline_1_v1',
        'duration_s': duration_s,
    }).encode()
    return base64.urlsafe_b64encode(blob).decode().rstrip('=')


def _video_url(name, duration_s):
    return f'https://scontent.cdninstagram.com/o1/v/{name}.mp4?efg={_efg(duration_s)}&oe=1'


def _post(code, username, *, videos=(), carousel=None, has_audio=True,
          media_type=2, caption='hello world'):
    post = {
        'code': code,
        'user': {'username': username, 'full_name': username.title()},
        'caption': {'text': caption} if caption else None,
        'taken_at': 1782587654,
        'like_count': 42,
        'original_width': 1296,
        'original_height': 720,
        'media_type': media_type,
        'has_audio': has_audio,
        'image_versions2': {'candidates': [
            {'url': 'https://scontent.cdninstagram.com/thumb_small.jpg', 'width': 150, 'height': 150},
            {'url': 'https://scontent.cdninstagram.com/thumb_big.jpg', 'width': 640, 'height': 640},
        ]},
    }
    if videos:
        post['video_versions'] = [
            {'type': 101 + i, 'url': url, 'width': None, 'height': None}
            for i, url in enumerate(videos)]
    if carousel is not None:
        post['carousel_media'] = carousel
    return post


def _page(posts, og_url=None):
    payload = {'data': {'data': {'edges': [
        {'node': {'thread_items': [{'post': post} for post in posts]}}]}}}
    head = f'<meta property="og:url" content="{og_url}" />' if og_url else ''
    return (
        f'<html><head>{head}</head><body>'
        '<script type="application/json">{"not":"a post"}</script>'
        '<script type="application/json">NOT VALID JSON AT ALL</script>'
        f'<script type="application/json">{json.dumps(payload)}</script>'
        '</body></html>')


def _extract(html, url):
    ie = ThreadsIE(YoutubeDL({'quiet': True, 'simulate': True}))
    ie._download_webpage = lambda *args, **kwargs: html
    return ie._real_extract(url)


class TestThreadsExtractor(unittest.TestCase):
    def test_selects_requested_post_not_first_on_page(self):
        html = _page([
            _post('OTHERPOST1', 'someone_else', videos=[_video_url('wrong', 55)]),
            _post('TARGETPOST', 'kfury', videos=[_video_url('right', 11)]),
        ])
        info = _extract(html, 'https://www.threads.com/@kfury/post/TARGETPOST')
        self.assertEqual(info['id'], 'TARGETPOST')
        self.assertEqual(info['duration'], 11)
        self.assertIn('right.mp4', info['formats'][0]['url'])

    def test_missing_post_raises_instead_of_returning_another(self):
        html = _page([_post('SOMEONEELSE', 'stranger', videos=[_video_url('wrong', 55)])])
        with self.assertRaisesRegex(ExtractorError, 'GONE12345'):
            _extract(html, 'https://www.threads.com/@zuck/post/GONE12345')

    def test_share_link_resolves_via_og_url(self):
        html = _page(
            [_post('REALCODE99', 'hunter', videos=[_video_url('shared', 36)])],
            og_url='https://www.threads.com/@hunter/post/REALCODE99')
        info = _extract(html, 'https://www.threads.com/share/_abc123/')
        self.assertEqual((info['id'], info['duration']), ('REALCODE99', 36))

    def test_unresolved_share_link_never_selects_another_post(self):
        html = _page([_post('SOMEONEELSE', 'stranger', videos=[_video_url('wrong', 55)])])
        with self.assertRaisesRegex(ExtractorError, 'Could not determine the post ID'):
            _extract(html, 'https://www.threads.com/share/_abc123/')

    def test_image_only_post_raises_clean_error(self):
        with self.assertRaisesRegex(ExtractorError, 'image post'):
            _extract(_page([_post('IMGPOST123', 'photog', media_type=1)]),
                     'https://www.threads.com/@photog/post/IMGPOST123')

    def test_carousel_returns_multi_video_playlist(self):
        carousel = [
            _post('C1', 'creator', videos=[_video_url('part1', 5)]),
            _post('C2', 'creator', videos=[_video_url('part2', 7)]),
        ]
        info = _extract(_page([_post('CAROUSEL01', 'creator', carousel=carousel, media_type=8)]),
                        'https://www.threads.com/@creator/post/CAROUSEL01')
        entries = list(info['entries'])
        self.assertEqual([entry['id'] for entry in entries], ['CAROUSEL01_1', 'CAROUSEL01_2'])

    def test_silent_and_duplicate_progressive_formats(self):
        same = 'https://scontent.cdninstagram.com/o1/v/same.mp4'
        info = _extract(_page([_post('DEDUP00001', 'user', has_audio=False,
                                     videos=[f'{same}?a=1', f'{same}?a=2'])]),
                        'https://www.threads.com/@user/post/DEDUP00001')
        self.assertEqual(len(info['formats']), 1)
        self.assertEqual(info['formats'][0]['acodec'], 'none')

    def test_metadata_thumbnails_and_efg_decoding(self):
        info = _extract(_page([_post('META000001', 'kfury', videos=[_video_url('v', 11)])]),
                        'https://www.threads.com/@kfury/post/META000001')
        self.assertEqual(info['uploader_url'], 'https://www.threads.com/@kfury')
        self.assertEqual(info['duration'], 11)
        self.assertEqual(len(info['thumbnails']), 2)
        self.assertEqual(ThreadsIE._efg_info('https://x/y.mp4?efg=!!!notbase64!!!'), {})

    def test_valid_url_matching(self):
        for url in (
            'https://www.threads.com/@user/post/ABC123',
            'https://www.threads.net/@user/post/ABC123',
            'https://threads.com/@user/post/ABC123',
            'https://www.threads.com/t/ABC123',
            'https://www.threads.com/share/ABC123/',
        ):
            self.assertTrue(ThreadsIE.suitable(url), url)
        self.assertFalse(ThreadsIE.suitable('https://www.threads.com/@user'))
