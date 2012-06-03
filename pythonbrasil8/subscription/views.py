# -*- coding: utf-8 -*-
import requests

from django.conf import settings
from django.contrib import messages
from django.http import HttpResponseRedirect, HttpResponse
from django.utils.decorators import method_decorator
from django.utils.translation import ugettext
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import View
from lxml import etree

from pythonbrasil8.core.views import LoginRequiredMixin
from pythonbrasil8.subscription.models import Subscription, Transaction


class SubscriptionView(LoginRequiredMixin, View):

    def generate_transaction(self, subscription):
        headers = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
        payload = settings.PAGSEGURO
        payload["itemAmount1"] = "%.2f" % 255
        payload["reference"] = "%d" % subscription.pk
        response = requests.post(settings.PAGSEGURO_CHECKOUT, data=payload, headers=headers)

        if response.ok:
            dom = etree.fromstring(response.content)
            transaction_code = dom.xpath("//code")[0].text

            transaction = Transaction.objects.create(
                subscription=subscription,
                code=transaction_code,
                status='pending',
            )
            return transaction
        return Transaction.objects.none()

    def get(self, request, *args, **kwargs):
        subscription = Subscription.objects.create(
            type='talk',
            user=request.user,
        )
        t = self.generate_transaction(subscription)

        # TODO: notify staff that it failed to generate the transation
        if not t:
            subscription.delete()
            messages.error(request, ugettext("Failed to generate a transaction within the payment gateway. Please contact the event staff to complete your registration."), fail_silently=True)
        else:
            messages.success(request, ugettext("You're one step closer to participate in PythonBrasil[8]! Now all you have to do is to pay the registration fee and you will be in!"), fail_silently=True)
        return HttpResponseRedirect("/dashboard/")


class NotificationView(View):

    def __init__(self, *args, **kwargs):
        self.methods_by_status = {
            3: self.transaction_done,
            7: self.transaction_canceled,
        }
        return super(NotificationView, self).__init__(*args, **kwargs)

    def transaction(self, transaction_code):
        url_transacao = "%s/%s?email=%s&token=%s" % (settings.PAGSEGURO_TRANSACTIONS, transaction_code, settings.PAGSEGURO[    "email"], settings.PAGSEGURO["token"])
        url_notificacao = "%s/%s?email=%s&token=%s" % (settings.PAGSEGURO_TRANSACTIONS_NOTIFICATIONS, transaction_code, settings.PAGSEGURO["email"], settings.PAGSEGURO["token"])

        response = requests.get(url_transacao)
        if not response.ok:
            response = requests.get(url_notificacao)
        if response.ok:
            dom = etree.fromstring(response.content)
            status_transacao = int(dom.xpath("//status")[0].text)
            referencia = int(dom.xpath("//reference")[0].text)
            return status_transacao, referencia
        return None, None

    def transaction_done(self, subscription_id):
        transaction = Transaction.objects.get(subscription_id=subscription_id)
        transaction.status = "done"
        transaction.save()

    def transaction_canceled(self, subscription_id):
        transaction = Transaction.objects.get(subscription_id=subscription_id)
        transaction.status = "canceled"
        transaction.save()

    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super(NotificationView, self).dispatch(*args, **kwargs)

    def post(self, request):
        notification_code = request.POST.get("notificationCode")

        if notification_code:
            status, subscription_id = self.transaction(notification_code)
            method = self.methods_by_status.get(status)

            if method:
                method(subscription_id)

        return HttpResponse("OK")
