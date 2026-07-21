import pytest

from switchgear.workflows.registry import WorkflowPlugins


def test_register_and_resolve():
    reg = WorkflowPlugins()
    gen, ex = object(), object()
    reg.register_generator("llm-brief", gen)
    reg.register_executor("send-digest", ex)
    assert reg.generator("llm-brief") is gen
    assert reg.executor("send-digest") is ex
    assert reg.generator_names == {"llm-brief"}
    assert reg.executor_names == {"send-digest"}


def test_unknown_names_raise_keyerror():
    reg = WorkflowPlugins()
    with pytest.raises(KeyError):
        reg.generator("nope")
    with pytest.raises(KeyError):
        reg.executor("nope")
