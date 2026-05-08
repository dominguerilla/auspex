from unittest.mock import MagicMock, patch


def make_mock_llm():
    llm = MagicMock()
    response = MagicMock()
    response.content = "query one"
    llm.invoke.return_value = response
    return llm


def test_build_graph_does_not_raise():
    with patch("agents.orchestrator.get_llm", return_value=make_mock_llm()), \
         patch("agents.reader.get_llm", return_value=make_mock_llm()), \
         patch("agents.critic.get_llm", return_value=make_mock_llm()), \
         patch("agents.refiner.get_llm", return_value=make_mock_llm()), \
         patch("agents.writer.get_llm", return_value=make_mock_llm()):
        from graph.graph_builder import build_graph
        build_graph()  # should not raise


def test_compiled_graph_has_invoke():
    with patch("agents.orchestrator.get_llm", return_value=make_mock_llm()), \
         patch("agents.reader.get_llm", return_value=make_mock_llm()), \
         patch("agents.critic.get_llm", return_value=make_mock_llm()), \
         patch("agents.refiner.get_llm", return_value=make_mock_llm()), \
         patch("agents.writer.get_llm", return_value=make_mock_llm()):
        from graph.graph_builder import build_graph
        graph = build_graph()
    assert hasattr(graph, "invoke")
    assert callable(graph.invoke)


def test_compiled_graph_has_stream():
    with patch("agents.orchestrator.get_llm", return_value=make_mock_llm()), \
         patch("agents.reader.get_llm", return_value=make_mock_llm()), \
         patch("agents.critic.get_llm", return_value=make_mock_llm()), \
         patch("agents.refiner.get_llm", return_value=make_mock_llm()), \
         patch("agents.writer.get_llm", return_value=make_mock_llm()):
        from graph.graph_builder import build_graph
        graph = build_graph()
    assert hasattr(graph, "stream")


def test_all_agent_nodes_present():
    with patch("agents.orchestrator.get_llm", return_value=make_mock_llm()), \
         patch("agents.reader.get_llm", return_value=make_mock_llm()), \
         patch("agents.critic.get_llm", return_value=make_mock_llm()), \
         patch("agents.refiner.get_llm", return_value=make_mock_llm()), \
         patch("agents.writer.get_llm", return_value=make_mock_llm()):
        from graph.graph_builder import build_graph
        graph = build_graph()
    node_names = set(graph.nodes)
    for expected in ["orchestrator", "searcher", "reader", "critic", "refiner", "writer"]:
        assert expected in node_names
