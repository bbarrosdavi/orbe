# kotlinx.serialization: os serializadores gerados são achados por reflexão
-keepclassmembers class io.hermes.orbe.** {
    *** Companion;
    kotlinx.serialization.KSerializer serializer(...);
}
