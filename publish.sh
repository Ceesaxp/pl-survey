#!/bin/sh

case $1 in
    local*)
	DST_ROOT=/srv/www
	DST_CGI=$DST_ROOT/cgi-bin
	DST_CSS=$DST_ROOT/htdocs/css
	DST_DATA=$DST_ROOT/cgi-bin/cgi-data
	;;
    remote*)
	DST_ROOT=//vkocmedb601/citiweb\$
	DST_CGI=$DST_ROOT/cgi-bin
	DST_CSS=$DST_ROOT/www/css
	DST_DATA=$DST_CGI/cgi-data
	;;
    *)
        echo -e "Usage:\n\tpublish.sh {local|remote}\n"
        exit
        ;;
esac

cp surveys.cgi $DST_CGI
cp cgi-data/surveys/*.xml $DST_DATA
cp css/surveys.css $DST_CSS

