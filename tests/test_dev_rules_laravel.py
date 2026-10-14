import tempfile
import unittest
from pathlib import Path

from prd_assistant.dev import rules_laravel

CONTROLLER = r'''<?php
namespace App\Http\Controllers\Api\V1;
use App\Http\Requests\Auth\LoginRequest;
use App\Http\Requests\Houses\UpdateHouseRequest;
class AuthController {
    public function login(LoginRequest $request) { return 1; }
    public function update(UpdateHouseRequest $request, House $house) { return 2; }
    public function logout() { return 3; }
    public function gone(MissingRequest $request) { return 4; }
}
'''
LOGIN = r'''<?php
namespace App\Http\Requests\Auth;
final class LoginRequest extends ApiRequest
{
    public const MAX = 200;
    public function rules(): array
    {
        return [
            'email' => ['required', 'string', 'email', 'max:255'],
            'password' => ['required', 'string', 'min:1', 'max:'.self::MAX],
            'role' => 'required|in:admin,tenant',
            'token' => ['sometimes', new PasswordPolicy()],
            'age' => ['nullable', 'integer', 'between:18,99'],
        ];
    }
    public function messages(): array
    {
        return ['email.required' => 'Please enter your email.'];
    }
}
'''
UPDATE = r'''<?php
namespace App\Http\Requests\Houses;
final class UpdateHouseRequest extends ApiRequest
{
    public function authorize(): bool
    {
        Gate::authorize('move', $house);
        return true;
    }
    public function rules(): array
    {
        $required = array_map(fn ($r) => $r, HouseRules::required());
        return [...$required, ...HouseRules::optional(), 'code' => ['string']];
    }
}
'''
HOUSE_RULES = r'''<?php
namespace App\Http\Requests\Houses;
final class HouseRules
{
    public static function optional(): array
    {
        return ['notes' => ['nullable', 'string', 'max:500']];
    }
}
'''


def line_of(text, needle):
    return next(i for i, l in enumerate(text.splitlines(), 1) if needle in l)


class LaravelRulesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        for rel, text in (("backend/app/Http/Requests/Auth/LoginRequest.php", LOGIN),
                          ("backend/app/Http/Requests/Houses/UpdateHouseRequest.php", UPDATE),
                          ("backend/app/Http/Requests/Houses/HouseRules.php", HOUSE_RULES)):
            p = Path(self.root) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)

    def rec(self, needle):
        return rules_laravel.read_request("backend/app/Http/Controllers/Api/V1/AuthController.php", CONTROLLER,
                                          line_of(CONTROLLER, needle), self.root)

    def test_rules_array_fields_and_limits(self):
        r = self.rec("function login(")
        fields = {f["name"]: f for f in r["fields"]}
        self.assertEqual(r["request_class"], "LoginRequest")
        self.assertEqual((fields["email"]["required"], fields["email"]["format"], fields["email"]["max"]), (True, "email", 255))
        self.assertEqual(fields["password"]["max"], 200)           # 'max:'.self::MAX resolved
        self.assertEqual(fields["role"]["one_of"], ["admin", "tenant"])   # pipe string form
        self.assertEqual((fields["age"]["min"], fields["age"]["max"], fields["age"]["required"]), (18, 99, False))

    def test_rule_objects_stay_raw_and_messages_attach_to_fields(self):
        r = self.rec("function login(")
        fields = {f["name"]: f for f in r["fields"]}
        self.assertIn("new PasswordPolicy()", " ".join(fields["token"]["raw"]))
        self.assertFalse(fields["token"]["required"])
        self.assertEqual(fields["email"]["messages"], ["Please enter your email."])

    def test_helper_spread_is_followed_one_level_and_variable_spread_is_not_read(self):
        r = self.rec("function update(")
        names = {f["name"] for f in r["fields"]}
        self.assertEqual(names, {"notes", "code"})
        self.assertTrue(any("$required" in n for n in r["not_read"]))
        self.assertEqual(r["authorize_checks"], ["move"])

    def test_handler_without_a_request_class_has_no_fields_and_nothing_unread(self):
        r = self.rec("function logout(")
        self.assertEqual((r["fields"], r["not_read"], r["request_class"]), ([], [], None))

    def test_missing_request_file_is_not_read(self):
        r = self.rec("function gone(")
        self.assertEqual(r["fields"], [])
        self.assertIn("MissingRequest", r["not_read"][0])

    def test_field_source_line_points_at_the_rule_entry(self):
        r = self.rec("function login(")
        email = next(f for f in r["fields"] if f["name"] == "email")
        self.assertEqual(email["source"], f"backend/app/Http/Requests/Auth/LoginRequest.php:{line_of(LOGIN, chr(39) + 'email' + chr(39) + ' =>')}")


if __name__ == "__main__":
    unittest.main()
