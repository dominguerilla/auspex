import pytest


def make_state(passed, iteration, max_iterations):
    return {
        "critique": {"passed": passed, "feedback": "", "missing_topics": []},
        "iteration": iteration,
        "max_iterations": max_iterations,
        "research_question": "",
        "search_queries": [],
        "search_results": [],
        "sources": [],
        "final_report": None,
        "messages": [],
    }


@pytest.mark.parametrize("passed,iteration,max_iterations,expected", [
    (True, 0, 3, "writer"),
    (True, 1, 3, "writer"),
    (True, 3, 3, "writer"),
    (False, 1, 3, "refiner"),
    (False, 2, 3, "refiner"),
    (False, 3, 3, "writer"),
    (False, 4, 3, "writer"),
])
def test_routing(passed, iteration, max_iterations, expected):
    from graph.edges import should_revise_or_write
    state = make_state(passed, iteration, max_iterations)
    assert should_revise_or_write(state) == expected


def test_return_type_is_str():
    from graph.edges import should_revise_or_write
    state = make_state(True, 0, 3)
    result = should_revise_or_write(state)
    assert isinstance(result, str)


def test_return_value_is_valid_node():
    from graph.edges import should_revise_or_write
    valid_nodes = {"refiner", "writer"}
    for passed in (True, False):
        for iteration in (0, 1, 3, 5):
            state = make_state(passed, iteration, 3)
            assert should_revise_or_write(state) in valid_nodes
