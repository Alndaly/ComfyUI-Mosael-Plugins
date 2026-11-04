"""随包的示例工作流:API 格式和界面格式说的是同一张图,H3 续写把尾巴锚在第 0 帧。"""

import json
from pathlib import Path

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _load(name):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def test_h3_continue_anchors_the_tail_at_frame_zero():
    api = _load("minimax_h3_continue_api.json")
    guide = next(node for node in api.values() if node["class_type"] == "MiniMaxH3AddGuide")
    assert guide["inputs"]["frame_idx"] == 0
    source = api[guide["inputs"]["image"][0]]
    assert source["class_type"] == "GetVideoComponents"
    assert guide["inputs"]["audio"] == [guide["inputs"]["image"][0], 1]
    assert api[source["inputs"]["video"][0]]["class_type"] == "LoadVideo"


def test_h3_continue_length_is_on_the_model_grid():
    api = _load("minimax_h3_continue_api.json")
    length = next(node for node in api.values() if node["class_type"] == "MiniMaxH3ImageToVideo")["inputs"]["length"]
    assert length % 17 == 5


def test_h3_continue_ui_and_api_are_the_same_graph():
    api = _load("minimax_h3_continue_api.json")
    ui = _load("minimax_h3_continue.json")
    assert {str(node["id"]): node["type"] for node in ui["nodes"]} == {key: node["class_type"] for key, node in api.items()}
    wired = {(str(link[3]), str(link[1]), link[2]) for link in ui["links"]}
    expected = {
        (key, value[0], value[1])
        for key, node in api.items()
        for value in node["inputs"].values()
        if isinstance(value, list)
    }
    assert wired == expected
