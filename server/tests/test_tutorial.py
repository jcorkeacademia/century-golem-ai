"""The interactive tutorial (server/tutorial.py), driven without a socket."""

import pytest

import tutorial as T
from century_engine import Game
from actions import build_action
from rooms import Room
from serialize import game_to_state


@pytest.fixture
def session():
    return T.TutorialSession("ABCD", "Ann", "amber")


# One right answer per objective, in OBJECTIVES order.
ANSWERS = [["Y", "Y"], ["G", "B"], ["Y", "G"]]


def go_to(session, step_id):
    """Click Next until `step_id`, completing the upgrade exercise and the
    scene 6 purchase (plus the opponent's reply) on the way."""
    while session.step_def["id"] != step_id:
        wait = session.step_def["wait"]
        if wait == "upgrade":
            todo = session.done.index(False)
            session.act({"type": "play_upgrade", "hand_index": 0, "upgrades": ANSWERS[todo]})
        elif wait == "action":
            session.act(session.recording["moves"][session.applied])
            session.replay_one()
            session.busy = False
        else:
            session.next()


# -- the recording -------------------------------------------------------------

def test_recording_replays_to_a_seat_0_win():
    rec = T.load_recording()
    game = Game(rec["players"], seed=rec["seed"])
    for msg in rec["moves"]:
        game.apply_action(build_action(msg))
    assert game.game_over
    assert game.winner() == rec["players"][0]


def test_recording_has_what_the_scenes_need():
    rec = T.load_recording()
    first = rec["moves"][0]
    assert first == {"type": "acquire", "row_index": 2, "payment": ["Y", "Y"]}   # scene 6
    game = Game(rec["players"], seed=rec["seed"])
    for msg in rec["moves"][:rec["handoff"]]:
        game.apply_action(build_action(msg))
    assert game.current == 0                                                    # scene 11
    mine, theirs = (len(p.point_cards) for p in game.players)
    assert mine >= 4 and theirs <= 3


# -- the upgrade exercise -------------------------------------------------------

def test_the_exercise_uses_the_caravan_already_on_screen(session):
    go_to(session, "upgrade")
    assert session.view()["stage_data"]["caravan"] == T.SHOWCASE_CARAVAN


@pytest.mark.parametrize("objective,answer", [
    (0, ["Y", "Y"]),
    (1, ["G", "B"]),
    (1, ["B", "G"]),          # the other order reaches the same caravan
    (2, ["Y", "G"]),
])
def test_upgrade_objective_accepts_right_answers(session, objective, answer):
    go_to(session, "upgrade")
    session.act({"type": "play_upgrade", "hand_index": 0, "upgrades": answer})
    assert session.feedback["ok"]
    assert session.done == [i == objective for i in range(len(T.OBJECTIVES))]


@pytest.mark.parametrize("answer", [
    ["B", "B"],
    ["G", "G"],
    ["M", "M"],               # illegal in the engine: magenta can't upgrade
])
def test_upgrade_objective_rejects_wrong_answers(session, answer):
    go_to(session, "upgrade")
    session.act({"type": "play_upgrade", "hand_index": 0, "upgrades": answer})
    assert not session.feedback["ok"]
    assert session.done == [False] * len(T.OBJECTIVES)
    assert tuple(session.sandbox.players[0].caravan) == T.UPGRADE_START   # reset for another go


def test_objectives_can_be_done_in_any_order(session):
    go_to(session, "upgrade")
    for i in (2, 0):
        session.act({"type": "play_upgrade", "hand_index": 0, "upgrades": ANSWERS[i]})
    assert session.done == [True, False, True]
    session.act({"type": "play_upgrade", "hand_index": 0, "upgrades": ANSWERS[2]})   # again
    assert not session.feedback["ok"] and session.step_def["id"] == "upgrade"
    session.act({"type": "play_upgrade", "hand_index": 0, "upgrades": ANSWERS[1]})
    assert session.step_def["id"] == "upgrade_recap"


def test_the_box_keeps_one_step_back(session):
    """Each step in the box shows the step before it, and only that one."""
    go_to(session, "upgrade")
    assert [e["id"] for e in session.view()["earlier"]] == ["order"]
    go_to(session, "upgrade_recap")
    assert [e["id"] for e in session.view()["earlier"]] == ["upgrade"]


def test_upgrade_needs_both_steps(session):
    go_to(session, "upgrade")
    with pytest.raises(T.TutorialError):
        session.act({"type": "play_upgrade", "hand_index": 0, "upgrades": ["Y"]})


def test_finishing_the_exercise_moves_on(session):
    go_to(session, "upgrade_recap")
    assert session.view()["stage_data"]["objectives"] == [
        {"text": t, "done": True} for t, _ in T.OBJECTIVES]


def test_the_exercise_never_touches_the_recorded_game(session):
    before = [p.caravan[:] for p in session.game.players]
    go_to(session, "upgrade_recap")
    assert [p.caravan for p in session.game.players] == before
    assert session.applied == 0


# -- scene 6: the paid purchase -----------------------------------------------------

@pytest.mark.parametrize("msg", [
    {"type": "acquire", "row_index": 0, "payment": []},
    {"type": "acquire", "row_index": 1, "payment": ["Y"]},
    {"type": "play_crystal", "hand_index": 0},
    {"type": "rest"},
    {"type": "nonsense"},
])
def test_scene_6_rejects_any_other_move(session, msg):
    go_to(session, "pay")
    with pytest.raises(T.TutorialError):
        session.act(msg)
    assert session.applied == 0


def test_scene_6_takes_the_recorded_move(session):
    go_to(session, "pay")
    view = session.view()
    assert view["target"] == {"kind": "acquire", "row_index": 2, "payment": ["Y", "Y"]}
    assert view["highlight_slot"] == 2
    assert session.act({"type": "acquire", "row_index": 2, "payment": ["Y", "Y"]}) == "reply"
    assert session.view()["wait"] == "busy"
    session.replay_one()          # what the async layer does after a pause
    session.busy = False
    assert session.step_def["id"] == "play_space"
    assert session.game.current == 0


def test_next_is_refused_where_an_action_is_expected(session):
    go_to(session, "pay")
    with pytest.raises(T.TutorialError):
        session.next()


def test_actions_are_refused_on_reading_steps(session):
    with pytest.raises(T.TutorialError):
        session.act({"type": "rest"})


# -- scene 11: the hand-off -----------------------------------------------------------

def test_fast_forward_then_free_play(session):
    go_to(session, "golems")
    assert session.next() == "fast_forward"
    while not session.at_handoff():
        session.replay_one()
    assert session.view()["wait"] == "free_play"
    assert session.game.current == 0
    # Free play is ordinary engine play: the recording's own next move is legal.
    msg = session.recording["moves"][session.applied]
    assert session.act(msg) == "bots"


# -- the field only exists here ---------------------------------------------------------

def test_tutorial_state_carries_the_field(session):
    state = session.state()
    assert state["tutorial"]["step"] == 1
    assert state["tutorial"]["total"] == len(T.STEPS)


def test_ordinary_rooms_have_no_tutorial_field():
    room = Room(room_id="ABCD", names=["Ann", "Bob"], avatars=["amber", "rust"])
    room.game = Game(room.names, seed=1)
    assert "tutorial" not in game_to_state(room, 0)


def test_tutorial_codes_show_the_painted_art():
    """The client gives tutorials 6-character codes (App.jsx) so the board
    and the staged cards show the painted set, not the photo set."""
    s = T.TutorialSession("ABCDEF", "Ann", "amber")
    state = s.state()
    arts = [c["art"] for c in state["shared"]["golem_row"] + state["shared"]["merchant_row"]]
    assert arts and all(a.startswith(("/static/golems-gol/", "/static/merchants-gol/")) for a in arts)
    go_to(s, "order")
    assert s.view()["stage_data"]["card"]["art"].startswith("/static/merchants-gol/")


def test_gem_order_keeps_the_caravan_text_above_it(session):
    """Scenes 2 and 3 share one box: scene 3 carries scene 2's words, so a
    refresh on scene 3 still shows both."""
    go_to(session, "caravan")
    assert session.view()["earlier"] == []
    caravan = T.STEPS[T.STEP_INDEX["caravan"]]
    go_to(session, "order")
    assert session.view()["earlier"] == [
        {"id": "caravan", "title": caravan["title"], "paragraphs": caravan["paragraphs"], "instruction": None, "refusal": None}]


def test_staged_cards_have_art(session):
    go_to(session, "card_types")
    cards = session.view()["stage_data"]["cards"]
    assert [c["card"]["name"] for c in cards] == list(T.SHOWCASE_CARDS)
    assert all(c["card"]["art"] for c in cards)


# -- boxes shared by two board steps ------------------------------------------------

@pytest.mark.parametrize("first,second", [("merchants", "pay"), ("played", "reset")])
def test_paired_steps_share_one_box(session, first, second):
    """The first step of a pair sends the second's words (`later`) so the box
    is sized for both from the start; the second sends the first's
    (`earlier`); both are placed against the same part of the board."""
    go_to(session, first)
    a = session.view()
    assert [e["id"] for e in a["later"]] == [second] and a["earlier"] == []
    go_to(session, second)
    b = session.view()
    assert [e["id"] for e in b["earlier"]] == [first] and b["later"] == []
    assert a["anchor"] == b["anchor"] is not None


def test_the_purchase_instruction_is_sized_in_advance(session):
    """The instruction the pay step shows is already in the merchants step's
    `later`, word for word, so the box doesn't change size."""
    go_to(session, "merchants")
    reserved = session.view()["later"][0]["instruction"]
    go_to(session, "pay")
    assert reserved == session.view()["instruction"]
    assert "yellow" in reserved and "3rd" in reserved


def test_the_turn_step_closes_the_opening_page(session):
    go_to(session, "turn")
    v = session.view()
    assert [e["id"] for e in v["earlier"]] == ["upgrade_recap"]
    assert v["stage_data"]["caravan"] == T.SHOWCASE_CARAVAN
