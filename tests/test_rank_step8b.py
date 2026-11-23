from test_rank import change, errlog, rank


def db_logs():
    return [errlog(402, "connection refused to db:8081") for _ in range(3)]


def test_kill_and_die_of_one_container_count_as_one_suspect():
    events = [
        change(398, "restart", "db", "container itb-db kill", action="kill",
               container="itb-db"),
        change(398.2, "restart", "db", "container itb-db die (exit 137)", action="die",
               exit_code="137", container="itb-db"),
    ] + db_logs()
    r = rank(events)
    assert len(r.suspects) == 1
    assert r.suspects[0].event.description.endswith("kill")
    assert any("counted once" in why for _, why in r.suppressed)


def test_two_kills_far_apart_are_two_suspects():
    events = [
        change(360, "restart", "db", "container itb-db kill #1", action="kill",
               container="itb-db"),
        change(398, "restart", "db", "container itb-db kill #2", action="kill",
               container="itb-db"),
    ] + db_logs()
    assert len(rank(events).suspects) == 2
