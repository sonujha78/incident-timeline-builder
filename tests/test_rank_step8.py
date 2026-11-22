from test_rank import change, incident, rank


def test_kill_stop_die_right_after_a_deploy_are_its_rollout():
    events = [change(380, desc="the deploy"),
              change(381, "restart", "web", "old kill", action="kill"),
              change(382, "restart", "web", "old die", action="die", exit_code="0"),
              change(383, "restart", "web", "old stop", action="stop")]
    r = rank(events)
    assert [s.event.description for s in r.suspects] == ["the deploy"]
    assert len(r.suppressed) == 3
    assert all("rollout" in why for _, why in r.suppressed)


def test_clean_exit_of_the_old_container_is_not_corroboration():
    events = [change(385, desc="the deploy"),
              change(386, "restart", "web", "old die", action="die", exit_code="0")]
    comps = {c.name: c for c in rank(events).suspects[0].components}
    assert comps["corroboration"].points == 0.0


def test_start_grace_widens_the_window_after_the_first_bad_probe():
    inc = incident(interval=1.0)
    events = [change(403, desc="slightly late")]
    assert rank(events, inc=inc).suspects == ()
    assert len(rank(events, inc=inc, start_grace_s=3).suspects) == 1


def test_oom_right_after_a_deploy_is_still_a_symptom():
    events = [change(380, desc="leaky deploy"),
              change(392, "restart", "web", "container itb-web OOM killed", action="oom")]
    r = rank(events)
    assert [s.event.description for s in r.suspects] == ["leaky deploy"]
    assert "symptom" in r.suppressed[0][1]
