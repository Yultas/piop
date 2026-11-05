import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router from './router'
import i18n from './i18n'
import reveal from './directives/reveal'
import App from './App.vue'

// Import E-Ink Typography & Theme Styles
import './styles/fonts.css'
import './styles/eink-theme.css'
import './styles/main.css'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)
app.use(i18n)

app.directive('reveal', reveal)

app.mount('#app')
