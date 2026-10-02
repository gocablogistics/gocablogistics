from django import forms
from .models import Rider


class UpgradeToDriverForm(forms.Form):
    username = forms.CharField(
        max_length=150, widget=forms.TextInput(attrs={"readonly": "readonly"})
    )
    email = forms.EmailField(widget=forms.EmailInput(attrs={"readonly": "readonly"}))
    phone_number = forms.RegexField(
        regex=r"^\d{11}$",
        max_length=11,
        error_messages={"invalid": "Enter a valid 11-digit phone number."},
        widget=forms.TextInput(attrs={"readonly": "readonly"}),
    )

    full_name = forms.CharField(max_length=255)
    date_of_birth = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    national_identification_number = forms.CharField(max_length=100)

    vehicle_type = forms.ChoiceField(choices=[("Bike", "Bike"), ("Bicycle", "Bicycle")])
    vehicle_model = forms.CharField(max_length=100)

    drivers_license = forms.FileField()
    vehicle_insurance = forms.FileField()
    vehicle_registration = forms.FileField()
    roadworthiness_certificate = forms.FileField()
    proof_of_residency = forms.FileField()
    passport_photo = forms.FileField()

    bank_name = forms.CharField(max_length=100)
    account_number = forms.RegexField(
        regex=r"^\d{10}$",
        error_messages={"invalid": "Account number must be 10 digits long."},
    )
    account_holder_name = forms.CharField(max_length=255)

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        if user:
            self.fields["username"].initial = user.username
            self.fields["email"].initial = user.email

            try:
                rider = Rider.objects.get(user=user)
                self.fields["phone_number"].initial = rider.phone_number
            except Rider.DoesNotExist:
                pass
