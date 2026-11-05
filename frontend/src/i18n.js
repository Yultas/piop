import { createI18n } from 'vue-i18n'
import ru from './locales/ru.json'
import en from './locales/en.json'

const savedLocale = localStorage.getItem('eink_locale') || 'ru'

export const i18n = createI18n({
  legacy: false,
  locale: savedLocale,
  fallbackLocale: 'en',
  messages: {
    ru,
    en
  }
})

export function setLocale(lang) {
  if (['ru', 'en'].includes(lang)) {
    i18n.global.locale.value = lang
    localStorage.setItem('eink_locale', lang)
    document.documentElement.setAttribute('lang', lang)
  }
}

export default i18n
