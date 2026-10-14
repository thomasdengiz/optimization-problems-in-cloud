"""End-to-end tests: the real web page talking to the real backend in a browser."""
from playwright.sync_api import Page, expect


def select_germany(page: Page) -> None:
    """Click Germany on the map (the only selectable country)."""
    page.locator("#map path.leaflet-interactive").first.click()
    expect(page.get_by_test_id("country-info")).to_contain_text("Deutschland")


def test_solve_is_disabled_until_germany_is_selected(app_page: Page):
    expect(app_page.get_by_test_id("solve-button")).to_be_disabled()

    select_germany(app_page)

    expect(app_page.get_by_test_id("solve-button")).to_be_enabled()


def test_only_germany_is_clickable_on_the_map(app_page: Page):
    assert app_page.locator("#map path.leaflet-interactive").count() == 1


def test_priority_list_small_day_shows_results_and_chart(app_page: Page):
    select_germany(app_page)
    app_page.get_by_test_id("method").select_option("priority_list")
    app_page.get_by_test_id("scenario").select_option("small")
    app_page.get_by_test_id("horizon").select_option("day")

    app_page.get_by_test_id("solve-button").click()

    expect(app_page.get_by_test_id("r-feasible")).to_have_text("ja", timeout=60000)
    expect(app_page.get_by_test_id("r-cost")).to_contain_text("€")
    expect(app_page.get_by_test_id("r-vars")).to_contain_text("binär")
    expect(app_page.get_by_test_id("chart")).to_be_visible()
    assert app_page.locator("#day option").count() == 1


def test_week_horizon_offers_seven_days(app_page: Page):
    select_germany(app_page)
    app_page.get_by_test_id("horizon").select_option("week")

    app_page.get_by_test_id("solve-button").click()

    expect(app_page.get_by_test_id("r-feasible")).to_be_visible(timeout=60000)
    assert app_page.locator("#day option").count() == 7


def test_exact_method_shows_gap_and_solver_time(app_page: Page):
    select_germany(app_page)
    app_page.get_by_test_id("method").select_option("exact")
    expect(app_page.get_by_test_id("time-limit")).to_be_visible()
    app_page.get_by_test_id("time-limit").fill("60")
    app_page.get_by_test_id("mip-gap").fill("5")

    app_page.get_by_test_id("solve-button").click()

    expect(app_page.get_by_test_id("r-feasible")).to_have_text("ja", timeout=120000)
    expect(app_page.get_by_test_id("r-solver-time")).to_contain_text("s")
    expect(app_page.get_by_test_id("r-gap")).not_to_have_text("")


def test_unimplemented_method_shows_placeholder_and_disables_solve(app_page: Page):
    select_germany(app_page)
    app_page.get_by_test_id("method").select_option("ea")

    expect(app_page.get_by_test_id("placeholder-note")).to_be_visible()
    expect(app_page.get_by_test_id("solve-button")).to_be_disabled()
