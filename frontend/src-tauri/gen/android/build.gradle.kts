buildscript {
    repositories {
        google()
        mavenCentral()
    }
    dependencies {
        classpath("com.android.tools.build:gradle:8.11.0")
        classpath("org.jetbrains.kotlin:kotlin-gradle-plugin:1.9.25")
        // Firebase Cloud Messaging (push notifications) — reads
        // app/google-services.json to bootstrap FirebaseApp at startup.
        // NOTE: gen/android is normally Tauri-generated; this edit (and the
        // matching `id("com.google.gms.google-services")` in app/build.gradle.kts)
        // is a one-time manual patch, not expected to be re-applied.
        classpath("com.google.gms:google-services:4.4.2")
    }
}

allprojects {
    repositories {
        google()
        mavenCentral()
    }
}

tasks.register("clean").configure {
    delete("build")
}

