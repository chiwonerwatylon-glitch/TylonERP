# The web pages call these methods by name through the JavaScript bridge.
-keepclassmembers class zw.co.tylonerp.** {
    @android.webkit.JavascriptInterface <methods>;
}
-keepattributes JavascriptInterface
