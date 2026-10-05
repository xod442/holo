"""Grouped navigation retains destinations, permissions, and visible identity."""
import pytest

from app import config
from app.web import templates
from conftest import login


@pytest.mark.parametrize("role", ["member_user", "manager_user", "admin_user"])
def test_navigation_groups_links_and_keeps_identity_outside_menu(client, request, role):
    user = request.getfixturevalue(role)
    login(client, user)
    page = client.get("/")
    assert 'aria-label="Main navigation"' in page.text
    assert 'aria-controls="primary-nav"' in page.text
    assert 'href="/" aria-current="page">Dashboard' in page.text
    assert 'href="/mallmanac"' in page.text
    assert 'href="/labs/new"' in page.text
    assert "<summary>Account</summary>" in page.text
    assert 'href="/account/password"' in page.text
    assert 'method="post" action="/logout"' in page.text
    header_after_nav = page.text.split("</nav>", 1)[1].split("</header>", 1)[0]
    assert 'aria-label="Signed-in user"' in header_after_nav
    assert f'<span class="account-email">{user.email}</span>' in header_after_nav
    assert f'<span class="account-role">{user.role}</span>' in header_after_nav
    for destination in ("/metrics", "/admin", "/admin/notifications", "/admin/log"):
        assert (f'href="{destination}"' in page.text) == (user.role != "member")
    assert ("<summary>Manage</summary>" in page.text) == (user.role != "member")


@pytest.mark.parametrize("path", ["/mallmanac", "/labs/new", "/metrics", "/admin", "/admin/notifications", "/admin/log", "/account/password"])
def test_current_destination_is_highlighted(client, admin_user, path):
    login(client, admin_user)
    page = client.get(path)
    assert page.status_code == 200
    assert f'href="{path}" aria-current="page"' in page.text
    assert 'href="/" aria-current="page"' not in page.text
    if path.startswith("/admin") or path == "/metrics":
        assert '<summary class="is-current">Manage</summary>' in page.text


def test_focus_launcher_and_root_prefix_preserved(client, member_user, monkeypatch):
    monkeypatch.setattr(config, "SSO_SHARED_SECRET", "test-navigation")
    monkeypatch.setattr(config, "ROOT_PATH", "/holo")
    monkeypatch.setitem(templates.env.globals, "rp", "/holo")
    login(client, member_user)
    page = client.get("/")
    assert 'href="/holo/go/focus"' in page.text
    assert 'href="/holo/mallmanac"' in page.text
    assert 'action="/holo/logout"' in page.text
    assert 'src="/holo/assets/navigation.js?' in page.text


def test_login_has_no_authenticated_navigation(client):
    page = client.get("/login")
    assert 'id="primary-nav"' not in page.text
    assert 'aria-label="Signed-in user"' not in page.text
