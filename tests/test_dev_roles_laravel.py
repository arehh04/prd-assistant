import unittest

from prd_assistant.dev import roles_laravel

ROUTES = r'''<?php
use Illuminate\Support\Facades\Route;

Route::get('/health', HealthController::class)->name('health');

Route::post('/auth/login', [AuthController::class, 'login'])
    ->middleware('throttle:login')->name('auth.login');

Route::middleware(['auth:sanctum', EnsureActiveSession::class, 'throttle:api-user'])->group(function (): void {
    Route::get('/auth/me', [AuthController::class, 'me'])->name('auth.me');

    Route::middleware('role:tenant')->group(function (): void {
        Route::get('/me/rooms', [TenantController::class, 'rooms']);
    });

    // Route::get('/commented', [X::class, 'y']);
    Route::middleware('role:super_admin,branch_admin')->group(function (): void {
        Route::get('/branches', [BranchController::class, 'index'])->name('branches.index');
        Route::scopeBindings()->group(function (): void {
            Route::get('/houses/{house}/rooms', [RoomController::class, 'index']);
        });
        Route::middleware('can:manage-billing')->get('/billing', [BillingController::class, 'index']);
        Route::get('/odd', [OddController::class, 'index'])->middleware('permission:x.y');
    });
});
'''
CONTROLLER = r'''<?php
class HouseController {
    public function update(UpdateHouseRequest $request, House $house) {
        $this->authorize('update', $house);
        Gate::authorize('move', $house);
        return 1;
    }

    public function index() { return 2; }
}
'''


def line_of(text, needle):
    return next(i for i, l in enumerate(text.splitlines(), 1) if needle in l)


class LaravelRolesTests(unittest.TestCase):
    def rec(self, needle):
        return roles_laravel.read_roles("routes/api.php", ROUTES, line_of(ROUTES, needle))

    def test_route_outside_any_group_is_undeclared_and_open(self):
        r = self.rec("'/health'")
        self.assertEqual((r["status"], r["undeclared_means"]), ("undeclared", "open"))

    def test_multi_line_statement_middleware_is_seen_but_not_a_role(self):
        r = self.rec("'/auth/login'")
        self.assertEqual(r["status"], "undeclared")
        self.assertIn("throttle:login", r["middleware"])

    def test_auth_group_means_signed_in(self):
        r = self.rec("'/auth/me'")
        self.assertEqual((r["status"], r["roles"], r["authenticated"]), ("read", None, True))

    def test_role_group_and_nesting(self):
        self.assertEqual(self.rec("'/me/rooms'")["roles"], ["tenant"])
        self.assertEqual(self.rec("'/branches'")["roles"], ["super_admin", "branch_admin"])
        nested = self.rec("'/houses/{house}/rooms'")
        self.assertEqual(nested["roles"], ["super_admin", "branch_admin"])
        self.assertTrue(nested["authenticated"])

    def test_ability_middleware_on_the_route_chain(self):
        r = self.rec("'/billing'")
        self.assertEqual(r["abilities"], ["manage-billing"])
        self.assertEqual(r["roles"], ["super_admin", "branch_admin"])

    def test_unknown_permission_middleware_inside_a_role_group_keeps_the_roles_and_notes_it(self):
        r = self.rec("'/odd'")
        self.assertEqual(r["roles"], ["super_admin", "branch_admin"])
        self.assertTrue(any("permission:x.y" in n for n in r["notes"]))

    def test_permission_middleware_alone_is_not_read(self):
        text = "<?php\nRoute::get('/p', [A::class, 'b'])->middleware('permission:x.y');\n"
        r = roles_laravel.read_roles("routes/api.php", text, 2)
        self.assertEqual(r["status"], "not_read")
        self.assertIn("permission:x.y", r["reason"])

    def test_commented_routes_do_not_create_groups_or_leak(self):
        text = "<?php\n// Route::middleware('role:x')->group(function () {\nRoute::get('/a', [A::class, 'b']);\n// });\n"
        self.assertEqual(roles_laravel.read_roles("routes/api.php", text, 3)["status"], "undeclared")

    def test_handler_checks(self):
        self.assertEqual(roles_laravel.handler_checks(CONTROLLER, line_of(CONTROLLER, "function update")), ["move", "update"])
        self.assertEqual(roles_laravel.handler_checks(CONTROLLER, line_of(CONTROLLER, "function index")), [])


if __name__ == "__main__":
    unittest.main()
