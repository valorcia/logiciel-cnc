import type { Locale } from "../i18n/config";

type Chrome = {
  greeting: (name?: string | null) => string;
  reasonMarketing: string;
  reasonTransactional: string;
  unsubscribe: string;
  soon: string;
};

/** The few strings the e-mail layout itself needs, per locale. */
export const emailStrings: Record<Locale, Chrome> = {
  en: {
    greeting: (n) => (n ? `Hi ${n},` : "Hi there,"),
    reasonMarketing: "You are receiving this e-mail because you joined the MILI Insider List and confirmed your address.",
    reasonTransactional: "You are receiving this e-mail because this address was entered on the MILI website.",
    unsubscribe: "Unsubscribe",
    soon: "soon",
  },
  fr: {
    greeting: (n) => (n ? `Bonjour ${n},` : "Bonjour,"),
    reasonMarketing: "Vous recevez cet e-mail parce que vous avez rejoint la MILI Insider List et confirmé votre adresse.",
    reasonTransactional: "Vous recevez cet e-mail parce que cette adresse a été saisie sur le site MILI.",
    unsubscribe: "Se désinscrire",
    soon: "bientôt",
  },
  de: {
    greeting: (n) => (n ? `Hallo ${n},` : "Hallo,"),
    reasonMarketing: "Sie erhalten diese E-Mail, weil Sie sich in die MILI Insider List eingetragen und Ihre Adresse bestätigt haben.",
    reasonTransactional: "Sie erhalten diese E-Mail, weil diese Adresse auf der MILI-Website eingegeben wurde.",
    unsubscribe: "Abmelden",
    soon: "bald",
  },
  es: {
    greeting: (n) => (n ? `Hola ${n}:` : "Hola:"),
    reasonMarketing: "Recibes este correo porque te uniste a la MILI Insider List y confirmaste tu dirección.",
    reasonTransactional: "Recibes este correo porque esta dirección se introdujo en el sitio web de MILI.",
    unsubscribe: "Darse de baja",
    soon: "pronto",
  },
  ja: {
    greeting: (n) => (n ? `${n} さん、こんにちは。` : "こんにちは。"),
    reasonMarketing: "MILI Insider List にご登録いただき、メールアドレスを確認されたため、このメールをお送りしています。",
    reasonTransactional: "MILI のウェブサイトでこのアドレスが入力されたため、このメールをお送りしています。",
    unsubscribe: "配信停止",
    soon: "近日",
  },
};
