from kivymd.app import MDApp
from kivy.lang import Builder
from kivy.core.window import Window
from kivymd.uix.button import MDFillRoundFlatIconButton,MDFlatButton,MDFloatingActionButton,MDIconButton,MDFillRoundFlatButton,MDRectangleFlatButton



class DemoApp(MDApp):
    title = "Kurama"
    icon = "icon.jpeg"
    def build(self):
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "Gray"
        Window.clearcolor = (0.2, 0.2, 0.2, 1)
        Window.clearcolor = (1,1,1,1)

        ##Button
        activate_kurama = MDFillRoundFlatIconButton()

        return 

    

DemoApp().run()
