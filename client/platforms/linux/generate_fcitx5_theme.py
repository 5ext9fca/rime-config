"""生成 Fcitx5 九宫格主题图（开发工具，需要 Pillow）。"""
import sys
from pathlib import Path
if not __package__:
    sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from pathlib import Path
import base64
import json
from PIL import Image, ImageDraw, ImageFilter, ImageChops

from client.project import ROOT as PROJECT_ROOT
ROOT = PROJECT_ROOT / 'config/fcitx5/themes'
SCALE = 4


def rounded(size, box, radius, color, outline=None):
    image = Image.new('RGBA', (size*SCALE, size*SCALE))
    ImageDraw.Draw(image).rounded_rectangle(tuple(int(v*SCALE) for v in box),
        radius*SCALE, fill=color, outline=outline, width=SCALE)
    return image


def margins(section, value):
    return f'[{section}]\nLeft={value}\nRight={value}\nTop={value}\nBottom={value}\n\n'


def main():
    for mode, background, text, green, border, shadow in (
        ('light', (255,255,255,230), '#000000', '#00b050', (144,144,144,36), 40),
        ('dark', (0,0,0,230), '#ffffff', '#008000', (255,255,255,48), 80),
    ):
        target = ROOT / ('hx-' + mode)
        target.mkdir(parents=True, exist_ok=True)
        image = rounded(96, (18,21,78,81), 12, (0,0,0,shadow)).filter(ImageFilter.GaussianBlur(6*SCALE))
        # Keep the shadow outside the panel; it must not increase panel opacity.
        mask = rounded(96, (18,18,78,78), 12, '#ffffff').getchannel('A')
        image.putalpha(ImageChops.subtract(image.getchannel('A'), mask))
        image = Image.alpha_composite(image, rounded(96, (18,18,78,78), 12, background, border))
        image.resize((96,96), Image.Resampling.LANCZOS).save(target/'panel.png')
        rounded(96, (18,18,78,78), 12, '#ffffff').resize((96,96), Image.Resampling.LANCZOS).save(target/'blur.png')
        rounded(24, (0,0,24,24), 7, green).resize((24,24), Image.Resampling.LANCZOS).save(target/'highlight.png')
        conf = f'''[Metadata]
Name=hx {mode}
Version=1
Author=hx
Description=Windows/macOS hx palette adapted for Fcitx5
ScaleWithDPI=True

[InputPanel]
NormalColor={text}
HighlightColor={text}
HighlightCandidateColor={text}
CandidateLabelColor={text}
HighlightCandidateLabelColor={text}
CandidateCommentColor={text}
HighlightCandidateCommentColor={text}
HighlightBackgroundColor=#00000000
LabelTextSizeFactor=100
CommentTextSizeFactor=100
EnableBlur=False
BlurMask=blur.png

[InputPanel/Background]
Image=panel.png

[InputPanel/Highlight]
Image=highlight.png

'''
        # Nine-slice image margins preserve rounded corners when resized.
        conf += margins('InputPanel/Background/Margin',30)
        conf += margins('InputPanel/BlurMargin',30)
        conf += margins('InputPanel/ShadowMargin',18)
        conf += margins('InputPanel/ContentMargin',22)
        conf += margins('InputPanel/TextMargin',5)
        conf += margins('InputPanel/Highlight/Margin',7)
        conf += f'''[Menu]
NormalColor={text}
HighlightCandidateColor={text}

[Menu/Background]
Image=panel.png

[Menu/Highlight]
Image=highlight.png

[Menu/Separator]
Color={text}30

'''
        conf += margins('Menu/Background/Margin',30)
        conf += margins('Menu/ContentMargin',22)
        conf += margins('Menu/TextMargin',5)
        conf += margins('Menu/Highlight/Margin',7)
        (target/'theme.conf').write_text(conf, encoding='utf-8')
    settings=dict(line.split('=',1) for line in (ROOT.parent/'classicui.conf').read_text().splitlines() if line and not line.startswith('#'))
    bundle={'version':1,'settings':settings,'files':{p.relative_to(ROOT).as_posix():base64.b64encode(p.read_bytes()).decode() for p in sorted(ROOT.glob('*/*')) if p.is_file()}}
    (ROOT.parent/'theme.json').write_text(json.dumps(bundle,indent=2)+'\n',encoding='utf-8')



if __name__ == '__main__':
    main()
