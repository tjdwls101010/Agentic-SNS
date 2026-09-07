"""_body.parse is a pure function; the coverage tally is what the output later depends on."""
import json

import pytest

from naver_blog_skill._body import parse
from naver_blog_skill._errors import NaverBlogError


def component(family, inner, extra=''):
    return f'<div class="se-component se-{family} se-l-default" {extra}>{inner}</div>'


def page(components, *, variables=True, tags='태그1,태그2', container='se-main-container', extra=''):
    head = ''
    if variables:
        head = f'''<script>
            var blogId = "testblog"; var blogNo = "999001"; var userId = "testviewer";
            var postTitle = "\\uD14C\\uC2A4\\uD2B8 \\uAE00"; var gsCategoryName = "테스트 카테고리";
            var openType = "3";
            {'var gsTagName = "' + tags + '";' if tags is not None else ''}
        </script>'''
    return f'''<!doctype html><html><body>
      {head}
      <div id="_post_property" logNo="99900000101" addDate="1757000000000" categoryNo="108"
           commentCount="8" browserTitle="브라우저 제목" editorversion="4"></div>
      <div class="{container}">{''.join(components)}</div>
      {extra}
    </body></html>'''


TEXT = component('text', '<p class="se-text-paragraph"><span>첫 문단입니다.</span></p>')
IMAGE = component('image', '<img data-lazy-src="https://blogfiles.pstatic.net/real.jpg" '
                           'src="https://blur.pstatic.net/placeholder.jpg">'
                           '<div class="se-caption">사진 설명</div>')


def test_the_page_variables_and_properties_become_the_post_metadata():
    doc = parse(page([TEXT]))
    assert doc.blog_id == 'testblog' and doc.blog_no == '999001' and doc.log_no == '99900000101'
    assert doc.viewer_id == 'testviewer'
    assert doc.title == '테스트 글'
    assert doc.created_at == '2025-09-05T00:33+09:00'
    assert doc.category_no == '108' and doc.category_name == '테스트 카테고리'
    assert doc.comment_count == 8
    assert doc.tags == ['태그1', '태그2']


def test_a_page_without_the_tag_variable_says_unknown_rather_than_no_tags():
    # "No tags" and "this reader could not find out" lead to different summaries.
    assert parse(page([TEXT], tags=None)).tags == 'unknown'
    assert parse(page([TEXT], tags='')).tags == []


def test_a_fully_understood_body_reports_no_reduction():
    doc = parse(page([TEXT, IMAGE, component('horizontalLine', '<hr>')]))
    assert doc.body.coverage.components == 3
    assert doc.body.coverage.full == 3 and doc.body.coverage.reduced == 0
    assert doc.body.coverage.label() == 'text[full]'
    assert doc.body.coverage.unhandled == []


def test_the_real_image_url_is_taken_and_the_blurred_placeholder_is_not():
    doc = parse(page([IMAGE]))
    assert doc.body.images == [{'url': 'https://blogfiles.pstatic.net/real.jpg', 'caption': '사진 설명'}]
    assert '[image: 사진 설명]' in doc.body.text


def test_an_image_link_supplies_the_url_when_the_lazy_attribute_is_absent():
    linked = component('image', '<a class="__se_image_link" '
                                'data-linkdata=\'{"src":"https://blogfiles.pstatic.net/linked.jpg"}\'>'
                                '<img src="https://blur.pstatic.net/x.jpg"></a>')
    doc = parse(page([linked]))
    # The anchor's link data names the real file; the img's src is the blurred placeholder.
    assert doc.body.images[0]['url'] == 'https://blogfiles.pstatic.net/linked.jpg'


FAMILIES = {
    'text': (TEXT, '첫 문단입니다.'),
    'sectionTitle': (component('sectionTitle', '<p><span>소제목</span></p>'), '## 소제목'),
    'quotation': (component('quotation', '<blockquote>인용문</blockquote>'), '> 인용문'),
    'documentTitle': (component('documentTitle', '<p><span>문서 제목</span></p>'), '문서 제목'),
    'horizontalLine': (component('horizontalLine', '<hr>'), '---'),
    'image': (IMAGE, '[image: 사진 설명]'),
    'imageStrip': (component('imageStrip', '<img data-lazy-src="https://a.pstatic.net/1.jpg">'), '[image]'),
    'imageGroup': (component('imageGroup', '<img data-lazy-src="https://a.pstatic.net/2.jpg">'), '[image]'),
    'sticker': (component('sticker', '<img src="https://a.pstatic.net/s.png">'), '[sticker]'),
    'table': (component('table', '<table><tr><td>가</td><td>나</td></tr></table>'), '가 | 나'),
    'oglink': (component('oglink', '<a data-linkdata=\'{"title":"링크 제목","link":"https://ex.com"}\'>x</a>'),
               'link: 링크 제목 (https://ex.com)'),
    'material': (component('material', '<a data-linkdata=\'{"type":"book","title":"책 이름",'
                                      '"link":"https://book.naver.com/1"}\'>x</a>'),
                 '[book: 책 이름 (https://book.naver.com/1)]'),
    'placesMap': (component('placesMap', '<script class="se-module-data" data-module=\''
                                         '{"type":"v2_map","data":{"name":"장소 이름"}}\'></script>'),
                  '[map: 장소 이름]'),
}


@pytest.mark.parametrize('family', sorted(FAMILIES))
def test_each_known_component_family_is_read_by_its_own_rule(family):
    markup, expected = FAMILIES[family]
    doc = parse(page([markup]))
    assert expected in doc.body.text, doc.body.text
    assert doc.body.coverage.full == 1 and doc.body.coverage.reduced == 0


def test_a_video_without_a_playable_url_keeps_it_null_rather_than_using_the_thumbnail():
    data = json.dumps({'type': 'v2_video',
                       'data': {'title': '영상 제목', 'thumbnail': 'https://a.pstatic.net/thumb.jpg'}})
    markup = component('video', f'<script class="se-module-data" data-module=\'{data}\'></script>')
    doc = parse(page([markup]))
    assert '[video: 영상 제목]' in doc.body.text
    attachment = doc.body.attachments[0]
    # A thumbnail is a picture of the video, not the video.
    assert attachment == {'kind': 'video', 'title': '영상 제목', 'url': None,
                          'thumbnail_url': 'https://a.pstatic.net/thumb.jpg'}


def test_an_oembed_is_not_assumed_to_be_a_video():
    data = json.dumps({'type': 'v2_oembed',
                       'data': {'inputUrl': 'https://x.com/someone/status/1', 'description': '소셜 글',
                                'thumbnailUrl': 'https://a.pstatic.net/t.jpg'}})
    markup = component('oembed', f'<script class="se-module-data" data-module=\'{data}\'></script>')
    doc = parse(page([markup]))
    assert '[embed: 소셜 글 (https://x.com/someone/status/1)]' in doc.body.text
    assert doc.body.attachments[0]['kind'] == 'embed'


def test_an_unfamiliar_family_keeps_what_it_can_and_says_it_was_reduced():
    markup = component('brandNewThing', '<p>남은 텍스트</p><img data-lazy-src="https://a.pstatic.net/n.jpg">')
    doc = parse(page([TEXT, markup]))
    assert '남은 텍스트' in doc.body.text
    assert doc.body.images[-1]['url'] == 'https://a.pstatic.net/n.jpg'
    assert doc.body.coverage.partial == 1 and doc.body.coverage.full == 1
    assert doc.body.coverage.unhandled == ['brandNewThing']
    assert doc.body.coverage.label() == 'text[partial: 1 of 2 components reduced]'


def test_a_component_nothing_can_be_taken_from_counts_as_lost():
    doc = parse(page([TEXT, component('mysteryThing', '<div></div>')]))
    assert doc.body.coverage.empty == 1
    assert 'mysteryThing' in doc.body.coverage.unhandled


def test_a_nested_component_is_owned_by_the_outer_one_and_not_counted_twice():
    nested = component('imageStrip', IMAGE + IMAGE)
    doc = parse(page([nested]))
    assert doc.body.coverage.components == 1
    assert len(doc.body.images) == 2


def test_broken_module_json_reduces_the_component_instead_of_failing_the_read():
    markup = component('video', '<script class="se-module-data" data-module=\'{not json\'></script>'
                                '<div>영상 자리</div>')
    doc = parse(page([TEXT, markup]))
    assert doc.body.coverage.components == 2
    # Losing the module fields is a reduction, and the tally has to say so.
    assert doc.body.coverage.partial == 1 and doc.body.coverage.full == 1
    assert 'video' in doc.body.coverage.unhandled


def test_a_module_wrapper_without_its_data_object_is_also_a_reduction():
    markup = component('oembed', '<script class="se-module-data" '
                                 'data-module=\'{"type":"v2_oembed"}\'></script>')
    doc = parse(page([TEXT, markup]))
    assert doc.body.coverage.partial == 1


def test_a_legacy_post_is_read_from_its_own_container():
    legacy = ('<div id="viewTypeSelector" class="post_ct">'
              '<p>첫 줄<br>둘째 줄<p>닫는 태그 없는 문단'
              '<img src="https://blogfiles.pstatic.net/legacy.jpg">'
              '<a href="https://example.com">바깥 링크</a>'
              '<a href="#anchor">앵커</a></div>')
    doc = parse(page([], container='nothing-here', extra=legacy))
    assert '첫 줄' in doc.body.text and '둘째 줄' in doc.body.text
    assert '닫는 태그 없는 문단' in doc.body.text
    assert doc.body.images[0]['url'] == 'https://blogfiles.pstatic.net/legacy.jpg'
    # A page anchor is not a link out of the post.
    assert [link['url'] for link in doc.body.links] == ['https://example.com']
    assert doc.body.coverage.label() == 'text[legacy]'


def test_when_both_containers_exist_the_editor_one_wins_if_it_has_components():
    legacy = '<div id="viewTypeSelector" class="post_ct">옛 본문</div>'
    doc = parse(page([TEXT], extra=legacy))
    assert '첫 문단입니다.' in doc.body.text and '옛 본문' not in doc.body.text


def test_an_empty_editor_container_falls_back_to_the_legacy_one_beside_it():
    # editorversion says 4 here and is wrong; the container that actually has content wins.
    legacy = '<div id="viewTypeSelector" class="post_ct">옛 본문이 실제 내용</div>'
    doc = parse(page([], extra=legacy))
    assert '옛 본문이 실제 내용' in doc.body.text


def test_a_page_with_no_body_container_at_all_is_a_shape_change():
    with pytest.raises(NaverBlogError) as caught:
        parse(page([], container='nothing-here'))
    assert caught.value.code == 6 and caught.value.error == 'envelope_drift'


def test_a_body_container_that_yields_nothing_is_not_reported_as_an_empty_post():
    empty = '<div id="viewTypeSelector" class="post_ct">   </div>'
    with pytest.raises(NaverBlogError) as caught:
        parse(page([], container='nothing-here', extra=empty))
    assert caught.value.code == 6


def test_scripts_and_styles_never_reach_the_text():
    markup = component('text', '<p>보이는 글</p><script>var secret = 1;</script>'
                               '<style>.a{color:red}</style>')
    doc = parse(page([markup]))
    assert 'secret' not in doc.body.text and 'color:red' not in doc.body.text


def test_whitespace_and_entities_are_normalized_and_blank_runs_collapse():
    markup = component('text', '<p>여백&nbsp;&nbsp;정리</p><p></p><p></p><p></p><p>다음</p>')
    doc = parse(page([markup]))
    assert '여백 정리' in doc.body.text
    assert '\n\n\n' not in doc.body.text


def test_an_empty_page_is_refused_rather_than_read_as_an_empty_post():
    for value in ('', '   ', None):
        with pytest.raises(NaverBlogError):
            parse(value)


def test_inline_markup_keeps_the_words_in_the_order_they_were_written():
    """Reading a node's own text before its children turns 앞<b>중간</b>뒤 into 앞뒤중간."""
    markup = component('text', '<p>앞<strong>중간</strong>뒤<br>다음</p>')
    doc = parse(page([markup]))
    assert doc.body.text == '앞중간뒤\n다음'


def test_a_stray_closing_tag_does_not_hide_the_components_after_it():
    """It closes the container in a browser too; what matters is not calling the rest text[full]."""
    inner = TEXT + '</div>' + component('text', '<p>뒤에 오는 문단</p>')
    doc = parse(page([inner]))
    assert '뒤에 오는 문단' in doc.body.text
    assert doc.body.coverage.components == 2
    assert doc.body.coverage.label().startswith('text[partial')
    assert 'outside-container' in doc.body.coverage.unhandled


def test_a_component_missing_its_closing_tag_loses_no_text():
    """Malformed nesting makes the component count approximate; it must not eat the words."""
    broken = '<div class="se-component se-text"><p>첫째</p>' + TEXT
    doc = parse(page([broken]))
    assert '첫째' in doc.body.text and '첫 문단입니다.' in doc.body.text


def test_a_thousand_unclosed_paragraphs_do_not_exhaust_the_stack():
    # Legacy Naver posts leave <p> open; treating that as nesting builds a stack thousands deep.
    legacy = ('<div id="viewTypeSelector" class="post_ct">'
              + ''.join(f'<p>문단 {index}' for index in range(1200)) + '</div>')
    doc = parse(page([], container='nothing-here', extra=legacy))
    assert '문단 0' in doc.body.text and '문단 1199' in doc.body.text


def test_the_module_shape_naver_actually_sends_is_the_one_that_is_read():
    video = json.dumps({'type': 'v2_video', 'data': {
        'thumbnail': 'https://phinf.pstatic.net/video.jpg', 'mediaMeta': {'title': '진짜 제목'}}})
    embed = json.dumps({'type': 'v2_oembed', 'data': {
        'description': '진짜 설명', 'inputUrl': 'https://example.com/watch',
        'thumbnailUrl': 'https://example.com/thumb.jpg'}})
    doc = parse(page([component('video', f'<script data-module=\'{video}\'></script>'),
                      component('oembed', f'<script data-module=\'{embed}\'></script>')]))
    assert '[video: 진짜 제목]' in doc.body.text
    assert '[embed: 진짜 설명 (https://example.com/watch)]' in doc.body.text
    kinds = {attachment['kind']: attachment for attachment in doc.body.attachments}
    assert kinds['video']['thumbnail_url'] == 'https://phinf.pstatic.net/video.jpg'
    assert kinds['embed']['url'] == 'https://example.com/watch'
    assert doc.body.coverage.full == 2


def test_module_json_that_is_valid_but_not_an_object_reduces_rather_than_crashes():
    for payload in ('[1]', '"a string"', 'null', '3'):
        markup = component('oembed', f'<script data-module=\'{payload}\'></script>')
        doc = parse(page([TEXT, markup]))
        assert doc.body.coverage.partial == 1, payload
        assert '첫 문단입니다.' in doc.body.text, payload


def test_link_data_that_is_not_an_object_does_not_crash_the_read():
    markup = component('oglink', '<a data-linkdata=\'["not","an","object"]\'>보이는 글자</a>')
    doc = parse(page([TEXT, markup]))
    assert '첫 문단입니다.' in doc.body.text


def test_a_picture_inside_a_text_component_is_not_silently_dropped():
    """Ownership stops double counting; it must not also hide what the owner did not read."""
    markup = component('text', '<p>글과 함께</p>' + IMAGE)
    doc = parse(page([markup]))
    assert doc.body.images and doc.body.images[0]['url'] == 'https://blogfiles.pstatic.net/real.jpg'
    assert doc.body.coverage.components == 1
    # Reading only the text of a component that also held a picture is a reduction.
    assert doc.body.coverage.partial == 1


def test_each_picture_in_a_group_keeps_its_own_caption():
    group = component('imageGroup',
                      '<div><img data-lazy-src="https://a.pstatic.net/1.jpg">'
                      '<div class="se-caption">첫 사진</div></div>'
                      '<div><img data-lazy-src="https://a.pstatic.net/2.jpg">'
                      '<div class="se-caption">둘째 사진</div></div>')
    doc = parse(page([group]))
    assert [image['caption'] for image in doc.body.images] == ['첫 사진', '둘째 사진']


def test_a_component_that_yields_only_a_link_counts_as_reduced_not_lost():
    markup = component('brandNewThing', '<a href="https://example.com">링크만</a>')
    doc = parse(page([TEXT, markup]))
    assert doc.body.coverage.empty == 0 and doc.body.coverage.partial == 1
    assert doc.body.links[-1]['url'] == 'https://example.com'


def test_a_body_that_survives_parsing_can_always_be_written_out():
    """A lone surrogate cannot be encoded as UTF-8; keeping one would fail the write, not the read."""
    markup = component('text', '<p>앞\ud800뒤​가운데</p>')
    doc = parse(page([markup]))
    assert doc.body.text == '앞뒤가운데'
    json.dumps(doc.to_dict(), ensure_ascii=False).encode('utf-8')


def test_entities_are_resolved_once_and_not_twice():
    # &amp;lt; means the literal text "&lt;", not a less-than sign.
    markup = component('text', '<p>&amp;lt;태그&amp;gt;</p>')
    doc = parse(page([markup]))
    assert doc.body.text == '&lt;태그&gt;'
