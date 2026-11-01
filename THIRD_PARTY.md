# Desktop plugin third-party materials

The bridge is AGPL-3.0-only. Third-party components retain their own licenses.
No model, font, or upstream library is modified by the plugin packaging scripts.

## Runtime and corresponding source

Runtime ZIPs include `third-party-licenses/`, `third-party-packages.json`,
`PYTHON-LICENSE.txt`, and the exact installed `requirements.txt`.
These preserve the wheel notices, including notices for bundled native libraries.

Each runtime has a matching `*-sources.zip` release asset containing the original
source distributions of its copyleft Python dependencies, MuPDF, GEOS and Python.
`SOURCES.json` records their upstream download URLs and SHA-256 hashes.
The bridge's exact source and build scripts are in the separate `*-source.zip`.
Use the included workflow, constraints and recorded requirements to rebuild.
Source archives are available at no charge alongside the binaries:
https://github.com/BigDawnGhost/wenyi-babeldoc-bridge/releases

Key upstream projects include:

- BabelDOC 0.5.20: https://github.com/funstory-ai/BabelDOC (AGPL-3.0)
- PyMuPDF/MuPDF 1.25.2: https://github.com/pymupdf/PyMuPDF and
  https://mupdf.com/ (AGPL-3.0)
- Levenshtein: https://github.com/rapidfuzz/Levenshtein (GPL-2.0-or-later)
- GEOS: https://libgeos.org/ (LGPL-2.1-or-later)
- PyInstaller: https://pyinstaller.org/ (GPL with bootloader exception)

## Offline assets

Asset bytes are verified against BabelDOC 0.5.20's embedded SHA3-256 hashes.
The model ZIP includes complete OFL, Apache and tokenizer license texts.
`licenses/FONT-COPYRIGHTS.md` reproduces the copyright and license metadata from
every bundled font; the fonts retain this metadata as well.

| Asset | Upstream and license |
| --- | --- |
| DocLayout-YOLO DocStructBench ONNX | https://huggingface.co/wybxc/DocLayout-YOLO-DocStructBench-onnx and https://huggingface.co/juliozhao/DocLayout-YOLO-DocStructBench — Apache-2.0 per both model cards |
| PP-OCRv4 detection ONNX | https://github.com/RapidAI/RapidOCR and https://github.com/PaddlePaddle/PaddleOCR — Apache-2.0, Copyright (c) 2016 PaddlePaddle Authors |
| o200k_base tokenizer | https://github.com/openai/tiktoken — MIT, Copyright (c) 2022 OpenAI, Shantanu Jain |
| Noto Sans/Serif | https://github.com/notofonts/latin-greek-cyrillic — OFL-1.1 |
| GoNoto Kurrent | https://github.com/satbyy/go-noto-universal — build tools under Unlicense; bundled Noto-derived fonts retain OFL-1.1 |
| Source Han Sans/Serif TrueType | https://github.com/Pal3love/Source-Han-TrueType — OFL-1.1 |
| Klee One | https://github.com/fontworks-fonts/Klee — OFL-1.1 |
| LXGW WenKai GB/TC | https://github.com/lxgw/LxgwWenKaiGB and https://github.com/lxgw/LxgwWenkaiTC — OFL-1.1 |
| Maru Buri | https://hangeul.naver.com/font — OFL-1.1; © NAVER Corp. © NAVER Cultural Foundation Corp. |

The official NAVER license also reserves the name **MaruBuri**:
https://help.naver.com/support/contents/contents.help?serviceNo=1074&categoryNo=3497

Copyright (c) 2010, NAVER Corporation (https://www.navercorp.com/) with Reserved
Font Name Nanum, Naver Nanum, NanumGothic, Naver NanumGothic, NanumMyeongjo,
Naver NanumMyeongjo, NanumBrush, Naver NanumBrush, NanumPen, Naver NanumPen,
Naver NanumGothicEco, NanumGothicEco, Naver NanumMyeongjoEco, NanumMyeongjoEco,
Naver NanumGothicLight, NanumGothicLight, NanumBarunGothic, Naver NanumBarunGothic,
NanumSquareRound, NanumBarunPen, MaruBuri, NanumSquareNeo.

This Font Software is licensed under the SIL Open Font License, Version 1.1.
See `licenses/OFL-1.1.txt`; the Klee copyright at the top of that copy applies
to Klee, while each other font's own copyright is in `FONT-COPYRIGHTS.md`.
