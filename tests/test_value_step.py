"""Value-aware budget: selling price + bank-flow transfers (no DB)."""

from fpl_engine.optimise.squad import selling_price
from fpl_engine.optimise.value_step import GwPlayer, value_aware_gw

GK, DEF, MID, FWD = 1, 2, 3, 4


def test_selling_price_rule():
    assert selling_price(50, 50) == 50          # no change
    assert selling_price(50, 90) == 50 + 20     # +40 rise -> +half (20)
    assert selling_price(50, 91) == 50 + 20     # +41 -> floor(20.5)=20
    assert selling_price(80, 70) == 70          # dropped -> current price


def _prior_pool(risen_current: int):
    players, prior, purchase = [], set(), {}

    def add(pid, pos, price, xp):
        players.append(GwPlayer(pid, pos, price, (pid % 6) + 1, xp))

    # 15-man prior squad, all bought at 50, low xP
    for pid, pos in ([(1, GK), (2, GK)] + [(p, DEF) for p in range(3, 8)]
                     + [(p, MID) for p in range(8, 13)] + [(p, FWD) for p in range(13, 16)]):
        add(pid, pos, 50, 4.0)
        prior.add(pid)
        purchase[pid] = 50
    # MID #12 has risen in price this GW
    players[[p.id for p in players].index(12)].price = risen_current
    # an expensive, high-xP MID target on a fresh club
    players.append(GwPlayer(100, MID, 120, 6, 20.0))
    return prior, purchase, players


def test_risen_value_funds_otherwise_unaffordable_transfer():
    # MID #12 rose 50 -> 200 (sell value 125); selling it funds the 120 target.
    prior, purchase, players = _prior_pool(risen_current=200)
    res = value_aware_gw(prior, purchase, bank=0, players=players, ft=1)
    assert res.feasible
    assert 100 in res.squad          # expensive target acquired
    assert 12 in res.transfers_out   # funded by selling the risen player
    assert res.bank >= 0
    assert res.purchase[100] == 120  # bought at current price


def test_flat_value_cannot_afford_same_transfer():
    # same target, but #12 did NOT rise (sell value 50) -> 0 + 50 < 120 = unaffordable
    prior, purchase, players = _prior_pool(risen_current=50)
    res = value_aware_gw(prior, purchase, bank=0, players=players, ft=1)
    assert res.feasible
    assert 100 not in res.squad      # cannot afford it without the value gain


def test_ft_value_blocks_marginal_transfer():
    # A held squad of 4.0-xP players + one slightly-better 4.6-xP target on a
    # fresh club. With a free transfer and no FT value, the 0.6 gain is taken;
    # with ft_value=1.0 the gain (<1.0) no longer justifies burning the transfer.
    prior, purchase, players = _prior_pool(risen_current=50)
    target = GwPlayer(100, MID, 50, 6, 4.2)        # affordable, tiny upgrade
    players = [p for p in players if p.id != 100] + [target]

    greedy = value_aware_gw(prior, purchase, bank=50, players=players, ft=1)
    assert 100 in greedy.transfers_in              # marginal upgrade taken

    disciplined = value_aware_gw(prior, purchase, bank=50, players=players, ft=1,
                                 ft_value=1.0)
    assert disciplined.transfers_in == []          # banked instead of churned


def test_ft_value_still_allows_clear_upgrade():
    prior, purchase, players = _prior_pool(risen_current=50)
    target = GwPlayer(100, MID, 50, 6, 20.0)       # big upgrade
    players = [p for p in players if p.id != 100] + [target]
    res = value_aware_gw(prior, purchase, bank=50, players=players, ft=1, ft_value=1.0)
    assert 100 in res.transfers_in                 # worth it despite FT value


def test_lock_holds_squad():
    prior, purchase, players = _prior_pool(risen_current=200)
    res = value_aware_gw(prior, purchase, bank=0, players=players, ft=1, lock=True)
    assert res.feasible
    assert set(res.squad) == prior   # no transfers under lock
    assert res.transfers_in == []
