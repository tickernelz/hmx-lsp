plugins {
    id("java")
    id("org.jetbrains.kotlin.jvm") version "1.9.22"
    id("org.jetbrains.intellij.platform") version "2.0.0"
}

group = "com.hashmicro.hmx"
version = "0.1.0"

repositories {
    mavenCentral()
    intellijPlatform {
        defaultRepositories()
    }
}

dependencies {
    intellijPlatform {
        pycharmCommunity("2024.1")
    }
}

kotlin {
    jvmToolchain(17)
}
